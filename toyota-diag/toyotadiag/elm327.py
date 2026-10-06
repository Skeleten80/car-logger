"""Low-level ELM327 serial driver.

Speaks the ELM327 AT command set over a serial port and returns raw
response text. This layer holds *no* vehicle-protocol assumptions: the
caller decides which init sequence to run (see protocols.py) and this
driver just moves bytes.

A custom ``serial_factory`` can be injected for tests.
"""

from __future__ import annotations

import time

import serial

PROMPT = b">"


class ELM327Error(Exception):
    """The adapter itself misbehaved (distinct from the car staying silent)."""


class ELM327:
    def __init__(
        self,
        port: str,
        baud: int = 38400,
        timeout: float = 3.0,
        serial_factory=None,
    ):
        factory = serial_factory or serial.Serial
        self._ser = factory(port, baudrate=baud, timeout=timeout)
        # pyserial exposes write_timeout only as a constructor kwarg; the
        # fake used in tests tolerates its absence.
        try:
            self._ser.write_timeout = timeout
        except AttributeError:
            pass
        self.timeout = timeout

    def close(self) -> None:
        try:
            self._ser.close()
        except Exception:
            pass

    def __enter__(self) -> "ELM327":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _read_until_prompt(self, extra_timeout: float = 0.0) -> bytes:
        buf = bytearray()
        deadline = time.monotonic() + self.timeout + extra_timeout
        while time.monotonic() < deadline:
            chunk = self._ser.read(1)
            if chunk:
                buf += chunk
                if buf.endswith(PROMPT):
                    break
        return bytes(buf)

    def command(self, cmd: str, extra_timeout: float = 0.0) -> str:
        """Send one AT command or OBD payload; return cleaned response text.

        Adapter-level states (``NO DATA``, ``?``, ``UNABLE TO CONNECT``,
        ``SEARCHING...``) are returned verbatim -- the prober logs them,
        it does not raise on them.
        """
        wire = cmd if cmd.endswith("\r") else cmd + "\r"
        try:
            self._ser.reset_input_buffer()
        except Exception:
            pass
        n = self._ser.write(wire.encode("ascii", errors="replace"))
        if n != len(wire):
            raise ELM327Error(f"short write: {n}/{len(wire)} bytes")
        raw = self._read_until_prompt(extra_timeout)
        if not raw:
            raise ELM327Error(f"no response from adapter to {cmd!r}")
        text = raw.decode("ascii", errors="replace")
        # Strip our own echo (present until ATE0) and the trailing prompt.
        text = text.replace(cmd.strip(), "", 1)
        text = text.replace(">", "")
        return " ".join(text.split())

    def reset(self) -> str:
        """ATZ: full adapter reset. Returns the version banner."""
        return self.command("ATZ", extra_timeout=2.0)
