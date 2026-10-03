"""USB GPS dongle reader (NMEA-0183 over serial).

Logs position fixes to the gps_fixes table on the same clock as the CAN
data, so a drive's route can be replayed against bus traffic afterwards.

Hardware note: this needs a USB GPS receiver (e.g. GlobalSat BU-353,
~$30 CAD) that presents as a serial port (/dev/ttyUSB0 on Linux,
/dev/cu.usbserial-* on macOS). The NMEA *parsing* below is pure logic and
is unit-tested; the serial *reading* path can't be exercised without the
dongle, so first run with real hardware deserves a watchful eye.

Usage:
    python -m carlogger.gps [--config config.local.toml]
"""
from __future__ import annotations

import argparse
import signal
import sys
import time

from .config import load_config
from .db import Store

_stop = False


def _handle_signal(signum, frame):
    global _stop
    _stop = True


def nmea_checksum_ok(line: str) -> bool:
    """Verify the *HH checksum trailer of an NMEA sentence."""
    line = line.strip()
    if not line.startswith("$") or "*" not in line:
        return False
    body, _, hexsum = line[1:].partition("*")
    try:
        expected = int(hexsum[:2], 16)
    except ValueError:
        return False
    actual = 0
    for ch in body:
        actual ^= ord(ch)
    return actual == expected


def _dm_to_deg(dm: str, hemi: str) -> float | None:
    """'4807.038,N' -> 48.1173; '01131.000,E' -> 11.5167.

    NMEA uses ddmm.mmm for latitude (N/S) and dddmm.mmm for longitude
    (E/W); the hemisphere disambiguates. Returns None on bad input.
    """
    if not dm or not hemi or hemi not in "NSEW":
        return None
    deg_digits = 2 if hemi in "NS" else 3
    try:
        deg = float(dm[:deg_digits])
        minutes = float(dm[deg_digits:])
    except ValueError:
        return None
    val = deg + minutes / 60.0
    return -val if hemi in "SW" else val


def parse_nmea(line: str) -> dict | None:
    """Parse one NMEA sentence into a fix dict, or None.

    Returns keys lat, lon (decimal degrees), alt_m, speed_kmh, sats --
    whichever the sentence carries. RMC gives position+speed, GGA gives
    position+altitude+satellites. Sentences with a bad checksum or void
    fix status are rejected.
    """
    line = line.strip()
    if not nmea_checksum_ok(line):
        return None
    fields = line[1:].split("*")[0].split(",")
    talker_type = fields[0][2:] if len(fields[0]) >= 5 else ""
    fix: dict = {}
    if talker_type == "RMC":
        if len(fields) < 10 or fields[2] != "A":
            return None  # void fix
        lat = _dm_to_deg(fields[3], fields[4])
        lon = _dm_to_deg(fields[5], fields[6])
        if lat is None or lon is None:
            return None
        fix["lat"] = lat
        fix["lon"] = lon
        try:
            fix["speed_kmh"] = float(fields[7]) * 1.852 if fields[7] else None
        except ValueError:
            fix["speed_kmh"] = None
    elif talker_type == "GGA":
        if len(fields) < 10 or fields[6] == "0":
            return None  # no fix
        lat = _dm_to_deg(fields[2], fields[3])
        lon = _dm_to_deg(fields[4], fields[5])
        if lat is None or lon is None:
            return None
        fix["lat"] = lat
        fix["lon"] = lon
        try:
            fix["alt_m"] = float(fields[9]) if fields[9] else None
        except ValueError:
            fix["alt_m"] = None
        try:
            fix["sats"] = int(fields[7]) if fields[7] else None
        except ValueError:
            fix["sats"] = None
    else:
        return None
    return fix


class GpsReader:
    """Reads NMEA sentences from a serial GPS and logs fixes.

    The serial port is opened lazily so unit tests can drive parse_nmea
    without hardware.
    """

    def __init__(self, cfg: dict):
        g = cfg.get("gps", {})
        self.port: str = g.get("port", "/dev/ttyUSB0")
        self.baud: int = int(g.get("baud", 9600))
        self.min_interval: float = float(g.get("min_interval", 1.0))
        self._ser = None

    def open(self) -> None:
        try:
            import serial  # pyserial; pip install pyserial
        except ImportError:
            raise SystemExit(
                "pyserial is not installed: pip install pyserial")
        self._ser = serial.Serial(self.port, self.baud, timeout=1.0)

    def close(self) -> None:
        if self._ser is not None:
            self._ser.close()
            self._ser = None

    def run(self, store: Store) -> None:
        """Read sentences until SIGINT/SIGTERM; log at most one fix per
        min_interval seconds (merging RMC+GGA fields)."""
        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)
        self.open()
        print(f"GPS reading {self.port} @ {self.baud} "
              f"-> {store.path} (session {store.session_id})", flush=True)
        pending: dict = {}
        last_log = 0.0
        try:
            while not _stop:
                raw = self._ser.readline()
                if not raw:
                    continue
                try:
                    line = raw.decode("ascii", errors="ignore")
                except Exception:
                    continue
                fix = parse_nmea(line)
                if not fix:
                    continue
                pending.update(fix)
                now = time.time()
                if ("lat" in pending and now - last_log >= self.min_interval):
                    last_log = now
                    store.log_gps(now, pending["lat"], pending["lon"],
                                  alt=pending.get("alt_m"),
                                  speed_kmh=pending.get("speed_kmh"),
                                  sats=pending.get("sats"))
                    pending = {}
        finally:
            self.close()
            store.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="USB GPS NMEA logger")
    ap.add_argument("--config", default="config.toml")
    args = ap.parse_args()
    cfg, cfg_path = load_config(args.config)
    print(f"using config: {cfg_path}", flush=True)
    store = Store(cfg["storage"]["path"], note="mode=gps")
    GpsReader(cfg).run(store)


if __name__ == "__main__":
    main()
