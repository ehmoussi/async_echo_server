from dataclasses import dataclass, field
import logging
import atexit
import ssl
from typing import Any, Generator

from aio import EventLoop, Future
import aio

HOSTNAME = "0.0.0.0"
PORT = 3000
CLIENTS_POOL: set["Client"] = set()
MAX_CLIENTS = 10


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("server")


@dataclass(eq=True, frozen=True)
class Client:
    hostname: str
    port: int
    sock: ssl.SSLSocket = field(hash=False)

    def addr_info(self) -> tuple[str, str]:
        return (self.hostname, str(self.port))


@atexit.register
def clean_pool() -> None:
    for client in CLIENTS_POOL:
        client.sock.shutdown(1)
        client.sock.close()
    CLIENTS_POOL.clear()


def echo_client(client: Client) -> Generator[Future[bytes], bytes | None, None]:
    loop = aio.get_event_loop()
    while True:
        try:
            data = yield from loop.read_all(client.sock)
        except Exception as e:
            logger.info(
                "%s has disconnect from the server for an unknown reason",
                client.addr_info(),
            )
            logger.debug("%s", e)
            if client in CLIENTS_POOL:
                CLIENTS_POOL.remove(client)
        else:
            if data == b"":
                logger.info("%s disconnect from the server", client.addr_info())
                if client in CLIENTS_POOL:
                    CLIENTS_POOL.remove(client)
                return None
            elif data is not None:
                logger.info(
                    "Received from %s: %s",
                    client.addr_info(),
                    data.decode(errors="replace"),
                )
                try:
                    client.sock.sendall(data + b"\n\n")
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
            elif client not in CLIENTS_POOL:
                break


def add_client(
    ssl_server_sock: ssl.SSLSocket,
) -> Generator[Future[ssl.SSLSocket], None, Client | None]:
    if len(CLIENTS_POOL) < MAX_CLIENTS:
        loop = aio.get_event_loop()
        sock = yield from loop.sock_accept(ssl_server_sock)
        if sock is not None:
            address_info = sock.getsockname()
            client = Client(address_info[0], address_info[1], sock)
            CLIENTS_POOL.add(client)
            logger.debug("Add client %s to the pool of clients")
            return client
    else:
        logger.warning(
            "Can't accept new connection. The maximum number of clients (%s) have been reached"
        )
        return None
    return None


def main() -> Generator[Future[Any], None, None]:
    global CLIENTS_POOL
    loop = aio.get_event_loop()
    with loop.create_server(
        HOSTNAME, PORT, MAX_CLIENTS, certfile="cert.pem", keyfile="key.pem"
    ) as ssl_server_sock:
        while True:
            client = yield from add_client(ssl_server_sock)
            if client is not None:
                loop.create_task(echo_client(client))


if __name__ == "__main__":
    EventLoop().run(main())
