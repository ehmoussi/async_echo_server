import ssl
from typing import Any, Generator

import aio
from aio import Future

HOSTNAME = "0.0.0.0"
PORT = 3000


def echo_server(
    sock: ssl.SSLSocket, input_data: str, end_of_stream: bytes = b"\n\n"
) -> Generator[Future[bytes], bytes | None, bytes | None]:
    loop = aio.get_event_loop()
    try:
        sock.sendall(input_data.encode(errors="replace") + end_of_stream)
    except Exception as e:
        print(f"Unexpectedly failed to send to the server {e}")
    data = yield from loop.read_all(sock)
    if data is not None:
        print(f"Received from the server: {data.decode(errors="replace")}")
    return data


def main() -> Generator[aio.Future[Any], ssl.SSLSocket, None]:
    loop = aio.get_event_loop()
    ssl_client_sock: ssl.SSLSocket | None = None
    try:
        ssl_client_sock = yield from loop.connect_client(HOSTNAME, PORT, "cert.pem")
        print("Echo server")
        while True:
            client_data = input()
            yield from echo_server(ssl_client_sock, client_data)
    finally:
        if ssl_client_sock is not None:
            ssl_client_sock.close()


if __name__ == "__main__":
    aio.EventLoop().run(main())
