import socket
import ssl

HOSTNAME = "0.0.0.0"
PORT = 3000


def main() -> None:
    context = ssl.create_default_context()
    context.load_verify_locations(cafile="cert.pem")
    context.check_hostname = False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_sock:
        client_sock.setblocking(False)
        while True:
            try:
                client_sock.connect((HOSTNAME, PORT))
            except BlockingIOError:
                pass
            except Exception:
                print(f"Failed to connect to {(HOSTNAME, PORT)}")
            else:
                is_connected = True
                break
        with context.wrap_socket(
            client_sock, do_handshake_on_connect=False, server_hostname=HOSTNAME
        ) as ssl_client_sock:
            ssl_client_sock.do_handshake(block=True)
            while True:
                try:
                    ssl_client_sock.do_handshake(block=False)
                except ssl.SSLWantReadError:
                    pass
                else:
                    break
            print("Echo server")
            while is_connected:
                client_data = input()
                ssl_client_sock.sendall(client_data.encode())
                server_data: bytes | None = None
                while True:
                    try:
                        recv_data = ssl_client_sock.recv(1024)
                    except ssl.SSLWantReadError:
                        if server_data is None:
                            continue
                        else:
                            break
                    except Exception:
                        server_data = None
                        is_connected = False
                        break
                    else:
                        if recv_data == b"":
                            server_data = None
                            is_connected = False
                            break
                        else:
                            if server_data is None:
                                server_data = b""
                            server_data += recv_data
                if server_data is not None:
                    print(f"Received from the server: {server_data.decode()}")


if __name__ == "__main__":
    main()
