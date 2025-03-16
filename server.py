import socket
import logging
import atexit

HOSTNAME = "0.0.0.0"
PORT = 3000
POOL_SOCKETS: dict[tuple[str, str], socket.socket] = {}
MAX_CLIENTS = 10

logging.basicConfig(level=logging.INFO)
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
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setblocking(False)
        s.bind((HOSTNAME, PORT))
        s.listen(MAX_CLIENTS)
        while True:
            if len(POOL_SOCKETS) < MAX_CLIENTS:
                try:
                    sock, addr_info = s.accept()
                except BlockingIOError:
                    pass
                else:
                    POOL_SOCKETS[addr_info] = sock
                    sock.setblocking(False)
                    logger.info(
                        "%s just connected (blocking: %s)",
                        addr_info,
                        sock.getblocking(),
                    )
            else:
                logger.warning(
                    "Can't accept the connection. The maximum number of clients (%s) have been reached"
                )
            for addr_info, sock in list(POOL_SOCKETS.items()):
                data: bytes | None = None
                try:
                    while True:
                        try:
                            recv_data = sock.recv(1024)
                        except BlockingIOError:
                            break
                        else:
                            if recv_data == b"":
                                del POOL_SOCKETS[addr_info]
                                logger.info("%s disconnect from the server", addr_info)
                                break
                            else:
                                if data is None:
                                    data = b""
                                data += recv_data
                except Exception:
                    logger.info(
                        "%s has disconnect from the server for an unknown reason",
                        addr_info,
                    )
                    del POOL_SOCKETS[addr_info]
                else:
                    if data is None:
                        continue
                    elif data == b"":
                        del POOL_SOCKETS[addr_info]
                        logger.info("%s disconnect from the server", addr_info)
                    else:
                        logger.info("Received from %s: %s", addr_info, data.decode())
                        sock.sendall(data)
                        logger.info("Send to %s: %s", addr_info, data.decode())


if __name__ == "__main__":
    main()
