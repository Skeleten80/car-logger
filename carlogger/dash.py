"""Phase-2 live dashboard server.

Serves the HTML dash plus a small JSON/SSE API, all fed by the SQLite DB
the logger writes -- no shared memory, the two processes only meet at
the database file. Run alongside the logger:

    python -m carlogger.dash [--config config.local.toml]

then open http://<mini>:8080/ from a phone or laptop on the same
network (the car's Wi-Fi hotspot in the real setup).

API (also consumed by the native CarDash SwiftUI app):
    GET /              the HTML dash
    GET /api/info      session id, configured DBC files, vehicle label
    GET /api/latest    latest OBD-II values + latest decoded signals
    GET /api/live      Server-Sent Events stream of /api/latest (~2 Hz)
    GET /api/history?signal=<name>&limit=<n>  time series for one signal
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .config import load_config

HTML_PATH = Path(__file__).with_name("dash.html")


def _connect(cfg: dict) -> sqlite3.Connection:
    path = Path(cfg["storage"]["path"]).expanduser()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _latest(conn: sqlite3.Connection, cfg: dict) -> dict:
    obd2: dict[str, float | None] = {}
    units: dict[str, str] = {}
    for row in conn.execute(
            "SELECT name, value, unit FROM obd2 WHERE id IN "
            "(SELECT MAX(id) FROM obd2 GROUP BY name)"):
        obd2[row["name"]] = row["value"]
        units[row["name"]] = row["unit"] or ""
    signals: dict[str, dict] = {}
    for row in conn.execute(
            "SELECT signal, value, unit, message FROM signals WHERE id IN "
            "(SELECT MAX(id) FROM signals GROUP BY signal)"):
        signals[row["signal"]] = {"value": row["value"],
                                  "unit": row["unit"] or "",
                                  "message": row["message"] or ""}
    ts_row = conn.execute(
        "SELECT MAX(ts) AS ts FROM "
        "(SELECT ts FROM obd2 UNION ALL SELECT ts FROM signals)").fetchone()
    return {"ts": ts_row["ts"] or time.time(),
            "obd2": obd2, "obd2_units": units, "signals": signals,
            "vision": _vision_summary(conn, cfg)}


def _history(conn: sqlite3.Connection, name: str,
             limit: int) -> dict:
    limit = max(1, min(limit, 5000))
    rows = conn.execute(
        "SELECT ts, value FROM signals WHERE signal=? "
        "ORDER BY ts DESC LIMIT ?", (name, limit)).fetchall()
    table = "signals"
    if not rows:
        rows = conn.execute(
            "SELECT ts, value FROM obd2 WHERE name=? "
            "ORDER BY ts DESC LIMIT ?", (name, limit)).fetchall()
        table = "obd2"
    samples = [[r["ts"], r["value"]] for r in reversed(rows)
               if r["value"] is not None]
    return {"signal": name, "table": table, "samples": samples}


def _vision_summary(conn: sqlite3.Connection, cfg: dict) -> dict:
    """Latest detection per label + recent event count + newest snapshot."""
    per_label: dict[str, dict] = {}
    for row in conn.execute(
            "SELECT label, confidence, ts FROM vision_events WHERE id IN "
            "(SELECT MAX(id) FROM vision_events GROUP BY label)"):
        per_label[row["label"]] = {"confidence": row["confidence"],
                                   "ts": row["ts"]}
    minute_ago = time.time() - 60
    n_recent = conn.execute(
        "SELECT COUNT(*) AS n FROM vision_events WHERE ts > ?",
        (minute_ago,)).fetchone()["n"]
    snap_row = conn.execute(
        "SELECT snapshot_path FROM vision_events "
        "WHERE snapshot_path != '' ORDER BY ts DESC LIMIT 1").fetchone()
    last_snapshot = None
    if snap_row and snap_row["snapshot_path"]:
        last_snapshot = Path(snap_row["snapshot_path"]).name
    return {"detections": per_label,
            "events_last_minute": n_recent,
            "last_snapshot": last_snapshot}


def _snapshot_path(cfg: dict, name: str) -> Path | None:
    """Resolve a snapshot filename safely inside the snapshot dir."""
    snap_dir = Path(cfg.get("vision", {}).get(
        "snapshot_dir", "~/car-logger-data/snapshots")).expanduser()
    p = (snap_dir / Path(name).name).resolve()
    if snap_dir.resolve() not in p.parents and p != snap_dir.resolve():
        return None
    return p if p.is_file() else None


def _dbc_files(cfg: dict) -> list[str]:
    p = cfg.get("decode", {}).get("dbc_path", "")
    if not p:
        return []
    path = Path(p).expanduser()
    if not path.exists():
        return []
    if path.is_file():
        return [path.name]
    return [f.name for f in sorted(path.rglob("*.dbc"))]


def _info(conn: sqlite3.Connection, cfg: dict) -> dict:
    row = conn.execute(
        "SELECT id, started_at FROM sessions ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return {
        "session_id": row["id"] if row else None,
        "started_ts": row["started_at"] if row else None,
        "dbc_files": _dbc_files(cfg),
        "vehicle": cfg.get("decode", {}).get("vehicle") or None,
    }


class _Handler(BaseHTTPRequestHandler):
    cfg: dict = {}

    def log_message(self, *args):  # quieter logs
        pass

    def _send_json(self, obj, status: int = 200) -> None:
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/":
                body = HTML_PATH.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif parsed.path == "/api/info":
                with _connect(self.cfg) as conn:
                    self._send_json(_info(conn, self.cfg))
            elif parsed.path == "/api/latest":
                with _connect(self.cfg) as conn:
                    self._send_json(_latest(conn, self.cfg))
            elif parsed.path == "/api/history":
                qs = parse_qs(parsed.query)
                name = qs.get("signal", [""])[0]
                limit = int(qs.get("limit", ["300"])[0] or 300)
                if not name:
                    self._send_json({"error": "missing ?signal="}, 400)
                    return
                with _connect(self.cfg) as conn:
                    self._send_json(_history(conn, name, limit))
            elif parsed.path == "/api/live":
                self._serve_sse()
            elif parsed.path.startswith("/snapshots/"):
                p = _snapshot_path(self.cfg, parsed.path[len("/snapshots/"):])
                if p is None:
                    self.send_error(404)
                    return
                body = p.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_error(404)
        except (BrokenPipeError, ConnectionResetError):
            pass  # client went away; nothing to do

    def _serve_sse(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            while True:
                with _connect(self.cfg) as conn:
                    payload = json.dumps(_latest(conn, self.cfg))
                chunk = f"data: {payload}\n\n".encode()
                self.wfile.write(chunk)
                self.wfile.flush()
                time.sleep(0.5)
        except (BrokenPipeError, ConnectionResetError):
            pass


def create_server(cfg: dict) -> ThreadingHTTPServer:
    _Handler.cfg = cfg
    d = cfg.get("dash", {})
    server = ThreadingHTTPServer((d.get("host", "127.0.0.1"),
                                  int(d.get("port", 8080))), _Handler)
    server.daemon_threads = True
    return server


def main() -> None:
    ap = argparse.ArgumentParser(description="Phase-2 live dashboard server")
    ap.add_argument("--config", default="config.toml")
    args = ap.parse_args()
    cfg, cfg_path = load_config(args.config)
    server = create_server(cfg)
    host, port = server.server_address
    print(f"dash serving {cfg_path} at http://{host}:{port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
