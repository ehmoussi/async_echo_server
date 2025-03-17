from dataclasses import dataclass, field
import logging
import selectors
import socket
import atexit
import ssl
from typing import Generator

from aio import Client, EventLoop, Future, Task
import aio

HOSTNAME = "0.0.0.0"
PORT = 3000
POOL_CLIENTS: set["Client"] = set()
MAX_CLIENTS = 10


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("server")


@atexit.register
def clean_pool() -> None:
    for client in POOL_CLIENTS:
        client.sock.shutdown(1)
        client.sock.close()
    POOL_CLIENTS.clear()


def read_client(client: Client) -> Generator[Future[bytes], bytes | None, bytes | None]:
    loop = aio.get_event_loop()
    data: bytes | None = None
    chunk_data = yield from loop.sock_recv(client)
    if chunk_data == b"":
        return b""
    while chunk_data is not None:
        if data is None:
            data = b""
        is_finished = chunk_data.endswith(b"\n\n")
        if is_finished:
            data += chunk_data[:-2]
            break
        else:
            data += chunk_data
            chunk_data = yield from loop.sock_recv(client)
            if chunk_data == b"":
                break
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
            if data == b"":
                logger.info("%s disconnect from the server", client.addr_info())
                if client in POOL_CLIENTS:
                    POOL_CLIENTS.remove(client)
                return None
            elif data is not None:
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


def add_client(
    ssl_server_sock: ssl.SSLSocket,
) -> Generator[Future[Client], None, Client | None]:
    if len(POOL_CLIENTS) < MAX_CLIENTS:
        loop = aio.get_event_loop()
        client = yield from loop.sock_accept(ssl_server_sock)
        if client is not None:
            POOL_CLIENTS.add(client)
            logger.debug("Add client %s to the pool of clients")
            return client
    else:
        logger.warning(
            "Can't accept new connection. The maximum number of clients (%s) have been reached"
        )
        return None
    return None


def main() -> Generator[Future[Client], None, None]:
    global POOL_CLIENTS
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
