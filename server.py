from dataclasses import dataclass, field
from selectors import DefaultSelector
import selectors
import socket
import logging
import atexit
import ssl
from typing import Any, Callable, Generator, Generic, TypeVar

HOSTNAME = "0.0.0.0"
PORT = 3000
POOL_CLIENTS: set["Client"] = set()
MAX_CLIENTS = 10
SELECTOR = DefaultSelector()


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("")

T = TypeVar("T")


class Future(Generic[T]):
    def __init__(self) -> None:
        self.result: T | None = None
        self._callbacks: list[Callable] = []

    def add_done_callback(self, callback: Callable) -> None:
        self._callbacks.append(callback)

    def set_result(self, result: T) -> None:
        self.result = result
        for callback in self._callbacks:
            callback(self)

    def __iter__(self) -> Generator["Future[T]", None, T]:
        yield self
        assert self.result is not None
        return self.result


class Task:
    def __init__(self, coroutine: Generator[Future[Any], Any, Any]) -> None:
        self.coroutine = coroutine
        future = Future[Any]()
        future.set_result(None)
        self.step(future)

    def step(self, future: Future[Any]) -> None:
        try:
            next_future = self.coroutine.send(future.result)
        except StopIteration:
            return
        else:
            next_future.add_done_callback(self.step)


@dataclass(eq=True, frozen=True)
class Client:
    hostname: str
    port: int
    sock: ssl.SSLSocket = field(hash=False)

    def addr_info(self) -> tuple[str, str]:
        return (self.hostname, str(self.port))


@atexit.register
def clean_pool():
    global POOL_CLIENTS
    for socket in POOL_CLIENTS:
        socket.sock.shutdown(1)
        socket.sock.close()
    POOL_CLIENTS = []


def accept_client(
    ssl_server_sock: ssl.SSLSocket,
) -> Generator[Future[Client], Client, Client | None]:
    if len(POOL_CLIENTS) < MAX_CLIENTS:
        future = Future[Client]()

        def on_accept() -> None:
            client_sock, addr_info = ssl_server_sock.accept()
            client_sock.setblocking(False)
            logger.info(
                "%s just connected (blocking: %s)", addr_info, client_sock.getblocking()
            )
            future.set_result(Client(addr_info[0], addr_info[1], client_sock))

        SELECTOR.register(ssl_server_sock.fileno(), selectors.EVENT_READ, on_accept)
        client = yield future
        SELECTOR.unregister(ssl_server_sock.fileno())
        return client
    else:
        logger.warning(
            "Can't accept the connection. The maximum number of clients (%s) have been reached"
        )
        return None


def read_socket(client: Client) -> Generator[Future[bytes], bytes, bytes | None]:
    future = Future[bytes]()

    def on_read() -> None:
        future.set_result(client.sock.recv(1024))

    SELECTOR.register(client.sock.fileno(), selectors.EVENT_READ, on_read)
    data: bytes | None = None
    try:
        logger.debug("Waiting for the client: %s", client.addr_info())
        data = yield future
        logger.debug("Received partial data for %s: %s", client.addr_info(), data)
    finally:
        SELECTOR.unregister(client.sock.fileno())
    if data == b"":
        logger.info("%s disconnect from the server", client.addr_info())
        if client in POOL_CLIENTS:
            POOL_CLIENTS.remove(client)
        return None
    return data


def read_client(client: Client) -> Generator[Future[bytes], bytes | None, bytes | None]:
    data: bytes | None = None
    chunk_data = yield from read_socket(client)
    while chunk_data is not None:
        if data is None:
            data = b""
        is_finished = chunk_data.endswith(b"\n\n")
        if is_finished:
            data += chunk_data[:-2]
            break
        else:
            data += chunk_data
            chunk_data = yield from read_socket(client)
    return data


def echo_client(client: Client) -> Generator[Future[bytes], bytes | None, None]:
    while True:
        try:
            data = yield from read_client(client)
        except Exception as e:
            logger.info(
                "%s has disconnect from the server for an unknown reason",
                client.addr_info(),
            )
            logger.debug("%s", e)
            if client in POOL_CLIENTS:
                POOL_CLIENTS.remove(client)
        else:
            if data is not None:
                logger.info(
                    "Received from %s: %s",
                    client.addr_info(),
                    data.decode(errors="replace"),
                )
                try:
                    client.sock.sendall(data)
                except Exception as e:
                    logger.info(
                        "Failed to send response to the client %s",
                        client.addr_info(),
                    )
                    logger.exception(e)
                else:
                    logger.info(
                        "Send to %s: %s",
                        client.addr_info(),
                        data.decode(errors="replace"),
                    )
            elif client not in POOL_CLIENTS:
                break


def event_loop() -> None:
    while True:
        try:
            events = SELECTOR.select()
        except OSError:
            logger.info("Failed to read the events of the registered sockets")
        else:
            for event_key, _ in events:
                callback = event_key.data
                callback()


def add_client(
    ssl_server_sock: ssl.SSLSocket,
) -> Generator[Future[Client], None, Client | None]:
    client = yield from accept_client(ssl_server_sock)
    if client is not None:
        POOL_CLIENTS.add(client)
        logger.debug("Add client %s to the pool of clients")
        return client
    return None


def main() -> Generator[Future[Client], None, None]:
    global POOL_CLIENTS
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(certfile="cert.pem", keyfile="key.pem")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_sock:
        server_sock.setblocking(False)
        server_sock.bind((HOSTNAME, PORT))
        server_sock.listen(MAX_CLIENTS)
        with context.wrap_socket(server_sock, server_side=True) as ssl_server_sock:
            while True:
                client = yield from add_client(ssl_server_sock)
                if client is not None:
                    Task(echo_client(client))


if __name__ == "__main__":
    Task(main())
    event_loop()
