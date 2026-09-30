"""Phase-2 DBC decode layer.

Loads .dbc files (e.g. from an opendbc checkout) and decodes raw CAN
frames into named, physically-scaled signals. cantools does the heavy
lifting; this module keeps the loading/decoding policy in one place.

On the Mac Mini:
    git clone --depth 1 --filter=blob:none --sparse \\
        https://github.com/commaai/opendbc.git
    cd opendbc && git sparse-checkout set opendbc
then point config [decode].dbc_path at the opendbc directory (or at the
single <make>_<model>_<year>.dbc for the car).
"""
from __future__ import annotations

from pathlib import Path

try:
    import cantools
except ImportError:  # pragma: no cover - surfaced with a clear error
    cantools = None


class SignalDB:
    """A set of loaded DBC databases; decode tries each in order."""

    def __init__(self) -> None:
        self.files: list[str] = []
        self._dbs: list = []

    def load(self, path: str | Path) -> int:
        """Load one .dbc file or every .dbc under a directory.

        Returns the number of files loaded. Raises RuntimeError if
        cantools is not installed, FileNotFoundError if path is missing.
        """
        if cantools is None:
            raise RuntimeError(
                "cantools is required for DBC decoding: "
                "pip install cantools")
        p = Path(path).expanduser()
        if not p.exists():
            raise FileNotFoundError(f"DBC path not found: {p}")
        dbc_files = [p] if p.is_file() else sorted(p.rglob("*.dbc"))
        loaded = 0
        for f in dbc_files:
            try:
                db = cantools.database.load_file(str(f))
            except Exception:
                continue  # not a parseable DBC; skip rather than die
            self._dbs.append(db)
            self.files.append(str(f))
            loaded += 1
        return loaded

    def decode(self, arb_id: int, data: bytes,
               is_extended: bool = False) -> dict[str, tuple[float, str, str]]:
        """Decode one frame.

        Returns {signal_name: (physical_value, unit, message_name)}.
        Empty dict when no loaded DBC defines this frame id, or the
        payload does not decode cleanly. Never raises.
        """
        if not self._dbs:
            return {}
        for db in self._dbs:
            try:
                msg = db.get_message_by_frame_id(arb_id)
            except KeyError:
                continue
            try:
                values = msg.decode(bytes(data), decode_choices=False,
                                    scaling=True)
            except Exception:
                continue
            out: dict[str, tuple[float, str, str]] = {}
            for sig in msg.signals:
                if sig.name in values:
                    v = values[sig.name]
                    if isinstance(v, (int, float)):
                        out[sig.name] = (float(v), sig.unit or "", msg.name)
            return out
        return {}
