from dataclasses import dataclass
from selectors import DefaultSelector
import socket
import logging
import atexit
import ssl

HOSTNAME = "0.0.0.0"
PORT = 3000
POOL_CLIENTS: list["Client"] = []
MAX_CLIENTS = 10

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("")


@dataclass()
class Client:
    hostname: str
    port: int
    sock: ssl.SSLSocket
    data: bytes | None = None

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
    else:
        logger.warning(
            "Can't accept the connection. The maximum number of clients (%s) have been reached"
        )


def read_client(index_client: int) -> bytes | None:
    client = POOL_CLIENTS[index_client]
    try:
        data = client.sock.recv(1024)
    except ssl.SSLWantReadError:
        return None
    else:
        if data == b"":
            logger.info("%s disconnect from the server", client.addr_info())
            del POOL_CLIENTS[index_client]
            return None
        else:
            return data


def echo_client(index_client: int) -> None:
    client = POOL_CLIENTS[index_client]
    client.data = None
    try:
        while True:
            recv_data = read_client(index_client)
            if recv_data is None:
                break
            else:
                if client.data is None:
                    client.data = b""
                client.data += recv_data
    except Exception as e:
        logger.info(
            "%s has disconnect from the server for an unknown reason",
            client.addr_info(),
        )
        logger.debug("%s", e)
        del POOL_CLIENTS[index_client]
    else:
        if client.data is not None:
            logger.info(
                "Received from %s: %s", client.addr_info(), client.data.decode()
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
                logger.info("Send to %s: %s", client.addr_info(), client.data.decode())



def main() -> None:
    global POOL_CLIENTS
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(certfile="cert.pem", keyfile="key.pem")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_sock:
        server_sock.setblocking(False)
        server_sock.bind((HOSTNAME, PORT))
        server_sock.listen(MAX_CLIENTS)
        with context.wrap_socket(server_sock, server_side=True) as ssl_server_sock:
            while True:
                accept_client(ssl_server_sock)
                for index_client, _ in enumerate(POOL_CLIENTS):
                    echo_client(index_client)


if __name__ == "__main__":
    main()
