"""SQLite storage for the phase-1 vehicle logger.

Tables:
  sessions   - one row per logger run
  raw_frames - every captured CAN frame (timestamp, arbitration ID, payload)
  obd2       - decoded OBD-II PID samples
  signals    - decoded DBC signals (phase 2)
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at REAL NOT NULL,
    note TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS raw_frames (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    ts REAL NOT NULL,
    arb_id INTEGER NOT NULL,
    is_extended INTEGER NOT NULL,
    dlc INTEGER NOT NULL,
    data_hex TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_raw_ts ON raw_frames(ts);
CREATE INDEX IF NOT EXISTS idx_raw_id ON raw_frames(arb_id);
CREATE TABLE IF NOT EXISTS obd2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    ts REAL NOT NULL,
    pid INTEGER NOT NULL,
    name TEXT DEFAULT '',
    value REAL,
    unit TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_obd2_ts ON obd2(ts);
CREATE INDEX IF NOT EXISTS idx_obd2_pid ON obd2(pid);
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    ts REAL NOT NULL,
    message TEXT DEFAULT '',
    signal TEXT NOT NULL,
    value REAL,
    unit TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_sig_name_ts ON signals(signal, ts);
CREATE TABLE IF NOT EXISTS vision_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    ts REAL NOT NULL,
    label TEXT NOT NULL,
    confidence REAL NOT NULL,
    x1 REAL NOT NULL,
    y1 REAL NOT NULL,
    x2 REAL NOT NULL,
    y2 REAL NOT NULL,
    snapshot_path TEXT DEFAULT '',
    interesting INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_vis_ts ON vision_events(ts);
CREATE INDEX IF NOT EXISTS idx_vis_label ON vision_events(label);
CREATE TABLE IF NOT EXISTS dtc_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    ts REAL NOT NULL,
    code TEXT NOT NULL,
    description TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'stored'
);
CREATE INDEX IF NOT EXISTS idx_dtc_code ON dtc_events(code);
CREATE TABLE IF NOT EXISTS gps_fixes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    ts REAL NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    alt REAL,
    speed_kmh REAL,
    sats INTEGER
);
CREATE INDEX IF NOT EXISTS idx_gps_ts ON gps_fixes(ts);
"""


class Store:
    """Buffered SQLite writer. Call flush()/close() to persist."""

    def __init__(self, path: str | Path, note: str = ""):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.executescript(SCHEMA)
        cur = self.conn.execute(
            "INSERT INTO sessions (started_at, note) VALUES (?, ?)",
            (time.time(), note),
        )
        self.session_id = cur.lastrowid
        self.conn.commit()
        self._raw_buf: list[tuple] = []
        self._obd_buf: list[tuple] = []
        self._sig_buf: list[tuple] = []
        self._vis_buf: list[tuple] = []
        self._dtc_buf: list[tuple] = []
        self._gps_buf: list[tuple] = []

    def log_frame(self, ts: float, arb_id: int, is_extended: bool,
                  dlc: int, data: bytes) -> None:
        self._raw_buf.append(
            (self.session_id, ts, arb_id, int(is_extended), dlc, data.hex()))
        if len(self._raw_buf) >= 500:
            self.flush()

    def log_obd2(self, ts: float, pid: int, name: str,
                 value: float | None, unit: str) -> None:
        self._obd_buf.append((self.session_id, ts, pid, name, value, unit))
        if len(self._obd_buf) >= 50:
            self.flush()

    def log_signals(self, ts: float,
                    rows: list[tuple[str, str, float | None, str]]) -> None:
        """Buffer decoded DBC signals; each row is
        (message_name, signal_name, value, unit)."""
        self._sig_buf.extend(
            (self.session_id, ts, msg, sig, val, unit)
            for msg, sig, val, unit in rows)
        if len(self._sig_buf) >= 200:
            self.flush()

    def flush(self) -> None:
        if self._raw_buf:
            self.conn.executemany(
                "INSERT INTO raw_frames "
                "(session_id, ts, arb_id, is_extended, dlc, data_hex) "
                "VALUES (?,?,?,?,?,?)", self._raw_buf)
            self._raw_buf.clear()
        if self._obd_buf:
            self.conn.executemany(
                "INSERT INTO obd2 (session_id, ts, pid, name, value, unit) "
                "VALUES (?,?,?,?,?,?)", self._obd_buf)
            self._obd_buf.clear()
        if self._sig_buf:
            self.conn.executemany(
                "INSERT INTO signals "
                "(session_id, ts, message, signal, value, unit) "
                "VALUES (?,?,?,?,?,?)", self._sig_buf)
            self._sig_buf.clear()
        if self._vis_buf:
            self.conn.executemany(
                "INSERT INTO vision_events "
                "(session_id, ts, label, confidence, x1, y1, x2, y2, "
                " snapshot_path, interesting) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)", self._vis_buf)
            self._vis_buf.clear()
        if self._dtc_buf:
            self.conn.executemany(
                "INSERT INTO dtc_events "
                "(session_id, ts, code, description, status) "
                "VALUES (?,?,?,?,?)", self._dtc_buf)
            self._dtc_buf.clear()
        if self._gps_buf:
            self.conn.executemany(
                "INSERT INTO gps_fixes "
                "(session_id, ts, lat, lon, alt, speed_kmh, sats) "
                "VALUES (?,?,?,?,?,?,?)", self._gps_buf)
            self._gps_buf.clear()
        self.conn.commit()

    def log_vision(self, ts: float,
                   rows: list[tuple[str, float, float, float, float, float,
                                    str, bool]]) -> None:
        """Buffer vision detections; each row is
        (label, confidence, x1, y1, x2, y2, snapshot_path, interesting)."""
        self._vis_buf.extend(
            (self.session_id, ts, label, conf, x1, y1, x2, y2, snap,
             int(interesting))
            for label, conf, x1, y1, x2, y2, snap, interesting in rows)
        if len(self._vis_buf) >= 200:
            self.flush()

    def close(self) -> None:
        self.flush()
        self.conn.close()

    def log_dtcs(self, ts: float,
                 rows: list[tuple[str, str, str]]) -> None:
        """Buffer DTC sightings; each row is (code, description, status)
        where status is 'stored' or 'pending'."""
        self._dtc_buf.extend(
            (self.session_id, ts, code, desc, status)
            for code, desc, status in rows)
        if len(self._dtc_buf) >= 20:
            self.flush()

    def log_gps(self, ts: float, lat: float, lon: float,
                alt: float | None = None,
                speed_kmh: float | None = None,
                sats: int | None = None) -> None:
        self._gps_buf.append(
            (self.session_id, ts, lat, lon, alt, speed_kmh, sats))
        if len(self._gps_buf) >= 60:
            self.flush()
