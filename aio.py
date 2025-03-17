import atexit
import contextlib
from dataclasses import dataclass, field
import logging
from selectors import DefaultSelector
import selectors
import socket
import ssl
from typing import Any, Callable, Generator, Generic, TypeAlias, TypeVar

T = TypeVar("T")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("aio")


Coroutine: TypeAlias = Generator["Future[Any]", Any, Any]


_LOOP: "EventLoop | None" = None


def get_event_loop() -> "EventLoop":
    if _LOOP is None:
        raise ValueError("There is no event loop currently running")
    return _LOOP


@dataclass(eq=True, frozen=True)
class Client:
    hostname: str
    port: int
    sock: ssl.SSLSocket = field(hash=False)

    def addr_info(self) -> tuple[str, str]:
        return (self.hostname, str(self.port))


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


class EventLoop:
    def __init__(self) -> None:
        self.selector = DefaultSelector()

    def run(self, coroutine: Coroutine) -> Any:
        global _LOOP
        _LOOP = self
        Task(coroutine)
        self.run_forever()

    def run_forever(self) -> None:
        while True:
            try:
                events = self.selector.select()
            except OSError:
                logger.info("Failed to read the events of the registered sockets")
            else:
                for event_key, _ in events:
                    callback = event_key.data
                    callback()

    def create_task(self, coroutine: Coroutine) -> Task:
        return Task(coroutine)

    @contextlib.contextmanager
    def create_server(
        self, hostname: str, port: int, max_clients: int, certfile: str, keyfile: str
    ) -> Generator[ssl.SSLSocket, None, None]:
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.load_cert_chain(certfile=certfile, keyfile=keyfile)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_sock:
            server_sock.setblocking(False)
            server_sock.bind((hostname, port))
            server_sock.listen(max_clients)
            with context.wrap_socket(server_sock, server_side=True) as ssl_server_sock:
                yield ssl_server_sock

    def sock_recv(
        self, client: Client, nbytes: int = 1024
    ) -> Generator[Future[bytes], bytes, bytes]:
        future = Future[bytes]()

        def on_read() -> None:
            future.set_result(client.sock.recv(nbytes))

        self.selector.register(client.sock.fileno(), selectors.EVENT_READ, on_read)
        data: bytes | None = None
        try:

            logger.debug("Waiting for the client: %s", client.addr_info())
            data = yield future
            logger.debug("Received partial data for %s: %s", client.addr_info(), data)
        finally:
            self.selector.unregister(client.sock.fileno())
        return data

    def sock_accept(
        self,
        sock: ssl.SSLSocket,
    ) -> Generator[Future[Client], Client, Client]:
        future = Future[Client]()

        def on_accept() -> None:
            client_sock, addr_info = sock.accept()
            client_sock.setblocking(False)
            logger.info(
                "%s just connected (blocking: %s)",
                addr_info,
                client_sock.getblocking(),
            )
            future.set_result(Client(addr_info[0], addr_info[1], client_sock))

        self.selector.register(sock.fileno(), selectors.EVENT_READ, on_accept)
        client = yield future
        self.selector.unregister(sock.fileno())
        return client
