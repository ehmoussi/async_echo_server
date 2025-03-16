from dataclasses import dataclass
from functools import partial
from selectors import DefaultSelector
import selectors
import socket
import logging
import atexit
import ssl

HOSTNAME = "0.0.0.0"
PORT = 3000
POOL_CLIENTS: list["Client"] = []
MAX_CLIENTS = 10
SELECTOR = DefaultSelector()


logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("")


@dataclass()
class Client:
    hostname: str
    port: int
    sock: ssl.SSLSocket
    data: bytes | None = None
    is_finished_reading: bool = True

    def addr_info(self) -> tuple[str, str]:
        return (self.hostname, str(self.port))


@atexit.register
def clean_pool():
    global POOL_CLIENTS
    for socket in POOL_CLIENTS:
        socket.sock.shutdown(1)
        socket.sock.close()
    POOL_CLIENTS = []


def accept_client(ssl_server_sock: ssl.SSLSocket) -> None:
    if len(POOL_CLIENTS) < MAX_CLIENTS:
        try:
            client_sock, addr_info = ssl_server_sock.accept()
        except BlockingIOError:
            pass
        except Exception:
            logger.info("A client failed to connect")
        else:
            POOL_CLIENTS.append(Client(addr_info[0], addr_info[1], client_sock))
            client_sock.setblocking(False)
            logger.info(
                "%s just connected (blocking: %s)",
                addr_info,
                client_sock.getblocking(),
            )
            SELECTOR.register(
                client_sock.fileno(),
                selectors.EVENT_READ,
                partial(echo_client, len(POOL_CLIENTS) - 1),
            )
    else:
        logger.warning(
            "Can't accept the connection. The maximum number of clients (%s) have been reached"
        )


def read_client(index_client: int) -> None:
    client = POOL_CLIENTS[index_client]
    try:
        data = client.sock.recv(1024)
    except ssl.SSLWantReadError:
        client.is_finished_reading = True
        return None
    else:
        if data == b"":
            logger.info("%s disconnect from the server", client.addr_info())
            SELECTOR.unregister(client.sock.fileno())
            del POOL_CLIENTS[index_client]
        else:
            logger.info("Received partial data for %s: %s", client.addr_info(), data)
            client.is_finished_reading = False
            if client.data is None:
                client.data = b""
            client.data += data
            # to check if the reading is finished
            read_client(index_client)


def echo_client(index_client: int) -> None:
    client = POOL_CLIENTS[index_client]
    try:
        read_client(index_client)
    except Exception as e:
        logger.info(
            "%s has disconnect from the server for an unknown reason",
            client.addr_info(),
        )
        logger.debug("%s", e)
        SELECTOR.unregister(client.sock.fileno())
        del POOL_CLIENTS[index_client]
    else:
        if client.data is not None and client.is_finished_reading:
            logger.info(
                "Received from %s: %s",
                client.addr_info(),
                client.data.decode(errors="replace"),
            )
            try:
                client.sock.sendall(client.data)
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
                    client.data.decode(errors="replace"),
                )
                # clean data
                client.data = None


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


def main() -> None:
    global POOL_CLIENTS
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(certfile="cert.pem", keyfile="key.pem")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_sock:
        server_sock.setblocking(False)
        server_sock.bind((HOSTNAME, PORT))
        server_sock.listen(MAX_CLIENTS)
        with context.wrap_socket(server_sock, server_side=True) as ssl_server_sock:
            SELECTOR.register(
                ssl_server_sock.fileno(),
                selectors.EVENT_READ,
                partial(accept_client, ssl_server_sock),
            )
            event_loop()


if __name__ == "__main__":
    main()
