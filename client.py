import socket

HOSTNAME = "0.0.0.0"
PORT = 3000


def main() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setblocking(False)
        while True:
            try:
                s.connect((HOSTNAME, PORT))
            except BlockingIOError:
                pass
            except Exception:
                print(f"Failed to connect to {(HOSTNAME, PORT)}")
            else:
                is_connected = True
                break
        print("Echo server")
        while is_connected:
            client_data = input()
            s.sendall(client_data.encode())
            server_data: bytes | None = None
            while True:
                try:
                    recv_data = s.recv(1024)
                except BlockingIOError:
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
