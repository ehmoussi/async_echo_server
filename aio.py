import contextlib
import logging
from selectors import DefaultSelector
import selectors
import socket
import ssl
from typing import Any, Callable, Generator, Generic, TypeAlias, TypeVar

T = TypeVar("T")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("aio")


Coroutine: TypeAlias = Generator["Future[Any]", Any, Any]


_LOOP: "EventLoop | None" = None


def get_event_loop() -> "EventLoop":
    if _LOOP is None:
        raise ValueError("There is no event loop currently running")
    return _LOOP


class Future(Generic[T]):
    def __init__(self) -> None:
        self.result: T | None = None
        self._callbacks: list[Callable[[Future[Any]], Any]] = []

    def add_done_callback(self, callback: Callable[["Future[Any]"], Any]) -> None:
        self._callbacks.append(callback)

    def set_result(self, result: T) -> None:
        self.result = result
        for callback in self._callbacks:
            callback(self)

    def __iter__(self) -> Generator["Future[T]", None, T]:
        yield self
        assert self.result is not None
        return self.result


class Task:
    def __init__(self, coroutine: Generator[Future[Any], Any, Any]) -> None:
        super().__init__()
        self.coroutine = coroutine
        future = Future[Any]()
        future.set_result(None)
        self.step(future)

    def step(self, future: Future[Any]) -> None:
        try:
            next_future = self.coroutine.send(future.result)
        except StopIteration:
            return
        else:
            next_future.add_done_callback(self.step)


class EventLoop:
    def __init__(self) -> None:
        self.selector = DefaultSelector()

    def run(self, coroutine: Coroutine) -> None:
        global _LOOP
        _LOOP = self
        Task(coroutine)
        self.run_forever()

    def run_forever(self) -> None:
        while True:
            try:
                events = self.selector.select()
            except OSError:
                logger.info("Failed to read the events of the registered sockets")
            else:
                for event_key, _ in events:
                    callback = event_key.data
                    callback()

    def create_task(self, coroutine: Coroutine) -> Task:
        return Task(coroutine)

    def connect_client(
        self, hostname: str, port: int, cafile: str
    ) -> Generator[Future[ssl.SSLSocket], ssl.SSLSocket, ssl.SSLSocket]:
        context = ssl.create_default_context()
        context.load_verify_locations(cafile=cafile)
        context.check_hostname = False
        client_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_sock.setblocking(False)
        ssl_client_sock = context.wrap_socket(
            client_sock, do_handshake_on_connect=False, server_hostname=hostname
        )
        yield from self.sock_connect(ssl_client_sock, hostname, port)
        yield from self.sock_do_handshake(ssl_client_sock)
        return ssl_client_sock

    @contextlib.contextmanager
    def create_server(
        self, hostname: str, port: int, max_clients: int, certfile: str, keyfile: str
    ) -> Generator[ssl.SSLSocket, None, None]:
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.load_cert_chain(certfile=certfile, keyfile=keyfile)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_sock:
            server_sock.setblocking(False)
            server_sock.bind((hostname, port))
            server_sock.listen(max_clients)
            with context.wrap_socket(server_sock, server_side=True) as ssl_server_sock:
                yield ssl_server_sock

    def read_all(
        self, sock: ssl.SSLSocket, end_of_stream: bytes = b"\n\n"
    ) -> Generator[Future[bytes], bytes | None, bytes | None]:
        data: bytes | None = None
        chunk_data = yield from self.sock_recv(sock)
        if chunk_data == b"":
            return b""
        while chunk_data is not None:
            if data is None:
                data = b""
            is_finished = chunk_data.endswith(end_of_stream)
            if is_finished:
                data += chunk_data[:-2]
                break
            else:
                data += chunk_data
                chunk_data = yield from self.sock_recv(sock)
                if chunk_data == b"":
                    break
        return data

    def sock_recv(
        self, sock: ssl.SSLSocket, nbytes: int = 1024
    ) -> Generator[Future[bytes], bytes, bytes]:
        future = Future[bytes]()

        def on_read() -> None:
            try:
                data = sock.recv(nbytes)
            except ssl.SSLWantReadError:
                pass
            else:
                future.set_result(data)

        self.selector.register(sock.fileno(), selectors.EVENT_READ, on_read)
        data: bytes | None = None
        try:

            logger.debug("Waiting for the client: %s", sock.getsockname())
            data = yield future
            logger.debug("Received partial data for %s: %s", sock.getsockname(), data)
        finally:
            self.selector.unregister(sock.fileno())
        return data

    def sock_accept(
        self,
        sock: ssl.SSLSocket,
    ) -> Generator[Future[ssl.SSLSocket], ssl.SSLSocket, ssl.SSLSocket]:
        future = Future[ssl.SSLSocket]()

        def on_accept() -> None:
            try:
                client_sock, addr_info = sock.accept()
            except Exception:
                pass
            else:
                client_sock.setblocking(False)
                logger.info(
                    "%s just connected (blocking: %s)",
                    addr_info,
                    client_sock.getblocking(),
                )
                future.set_result(client_sock)

        self.selector.register(sock.fileno(), selectors.EVENT_READ, on_accept)
        client = yield future
        self.selector.unregister(sock.fileno())
        return client

    def sock_connect(
        self, sock: ssl.SSLSocket, hostname: str, port: int
    ) -> Generator[Future[ssl.SSLSocket], ssl.SSLSocket, ssl.SSLSocket]:
        try:
            sock.connect((hostname, port))
        except BlockingIOError:
            pass

        future = Future[ssl.SSLSocket]()

        def on_connect() -> None:
            sock.connect((hostname, port))
            future.set_result(sock)

        self.selector.register(sock.fileno(), selectors.EVENT_WRITE, on_connect)
        yield future
        self.selector.unregister(sock.fileno())
        return sock

    def sock_do_handshake(
        self, sock: ssl.SSLSocket
    ) -> Generator[Future[ssl.SSLSocket], ssl.SSLSocket, ssl.SSLSocket]:
        try:
            sock.do_handshake(block=False)
        except ssl.SSLWantReadError:
            pass

        future = Future[ssl.SSLSocket]()

        def on_connect() -> None:
            sock.do_handshake(block=False)
            future.set_result(sock)

        self.selector.register(sock.fileno(), selectors.EVENT_READ, on_connect)
        yield future
        self.selector.unregister(sock.fileno())
        return sock
