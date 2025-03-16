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
                for addr_info, client_sock in list(POOL_SOCKETS.items()):
                    data: bytes | None = None
                    try:
                        while True:
                            try:
                                recv_data = client_sock.recv(1024)
                            except ssl.SSLWantReadError:
                                break
                            else:
                                if recv_data == b"":
                                    del POOL_SOCKETS[addr_info]
                                    logger.info(
                                        "%s disconnect from the server", addr_info
                                    )
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
                        if data is None:
                            continue
                        elif data == b"":
                            del POOL_SOCKETS[addr_info]
                            logger.info("%s disconnect from the server", addr_info)
                        else:
                            logger.info(
                                "Received from %s: %s", addr_info, data.decode()
                            )
                            client_sock.sendall(data)
                            logger.info("Send to %s: %s", addr_info, data.decode())


if __name__ == "__main__":
    main()
