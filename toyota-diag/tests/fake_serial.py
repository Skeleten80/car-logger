"""Shared fake serial port for tests: scripted adapter responses."""


class FakeSerial:
    """Mimics the pyserial API surface used by ELM327.

    Queue full adapter replies (without the trailing '>'); read() serves
    them byte-by-byte until each reply's prompt is consumed.
    """

    def __init__(self, port, baudrate=38400, timeout=1.0, **kwargs):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self._queued: list[bytes] = []
        self.written: list[bytes] = []
        self.closed = False

    def queue(self, *replies: str) -> "FakeSerial":
        for reply in replies:
            self._queued.append((reply + ">").encode("ascii"))
        return self

    # -- pyserial API used by the driver ------------------------------------
    def write(self, data: bytes) -> int:
        self.written.append(data)
        return len(data)

    def read(self, n: int = 1) -> bytes:
        if not self._queued:
            return b""
        chunk = self._queued[0][:n]
        self._queued[0] = self._queued[0][n:]
        if not self._queued[0]:
            self._queued.pop(0)
        return chunk

    def reset_input_buffer(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True
