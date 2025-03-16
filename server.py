import socket
import logging
import atexit
import ssl

HOSTNAME = "0.0.0.0"
PORT = 3000
POOL_SOCKETS: dict[tuple[str, str], ssl.SSLSocket] = {}
MAX_CLIENTS = 10

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("")


@atexit.register
def clean_pool():
    global POOL_SOCKETS
    for sock in POOL_SOCKETS.values():
        sock.shutdown(1)
        sock.close()
    POOL_SOCKETS = {}


def accept_client(ssl_server_sock: ssl.SSLSocket) -> None:
    if len(POOL_SOCKETS) < MAX_CLIENTS:
        try:
            client_sock, addr_info = ssl_server_sock.accept()
        except BlockingIOError:
            pass
        except Exception:
            logger.info("A client failed to connect")
        else:
            POOL_SOCKETS[addr_info] = client_sock
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


def read_client(addr_info: tuple[str, str]) -> bytes | None:
    client_sock = POOL_SOCKETS[addr_info]
    try:
        data = client_sock.recv(1024)
    except ssl.SSLWantReadError:
        return None
    else:
        if data == b"":
            del POOL_SOCKETS[addr_info]
            logger.info("%s disconnect from the server", addr_info)
            return None
        else:
            return data


def echo_client(addr_info: tuple[str, str]) -> None:
    client_sock = POOL_SOCKETS[addr_info]
    data: bytes | None = None
    try:
        while True:
            recv_data = read_client(addr_info)
            if recv_data is None:
                break
            else:
                if data is None:
                    data = b""
                data += recv_data
    except Exception as e:
        logger.info(
            "%s has disconnect from the server for an unknown reason",
            addr_info,
        )
        logger.debug("%s", e)
        del POOL_SOCKETS[addr_info]
    else:
        if data is not None:
            logger.info("Received from %s: %s", addr_info, data.decode())
            try:
                client_sock.sendall(data)
            except Exception as e:
                logger.info(
                    "Failed to send response to the client %s",
                    addr_info,
                )
                logger.exception(e)
            else:
                logger.info("Send to %s: %s", addr_info, data.decode())


def main() -> None:
    global POOL_SOCKETS
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(certfile="cert.pem", keyfile="key.pem")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_sock:
        server_sock.setblocking(False)
        server_sock.bind((HOSTNAME, PORT))
        server_sock.listen(MAX_CLIENTS)
        with context.wrap_socket(server_sock, server_side=True) as ssl_server_sock:
            while True:
                accept_client(ssl_server_sock)
                for addr_info in list(POOL_SOCKETS.keys()):
                    echo_client(addr_info)


if __name__ == "__main__":
    main()
