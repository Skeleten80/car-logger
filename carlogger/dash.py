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
    GET /api/latest[?session_id=N]   latest OBD-II values + decoded signals
    GET /api/live      Server-Sent Events stream of /api/latest (~2 Hz)
    GET /api/history?signal=<name>&limit=<n>[&session_id=N]
    GET /api/sessions  all sessions, newest first, with sample counts
    GET /api/trip?session_id=N      drive summary (distance, economy, events)
    GET /api/track?session_id=N     decimated GPS track [[lat, lon], ...]
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
from . import trips as trip_analytics

HTML_PATH = Path(__file__).with_name("dash.html")


def _connect(cfg: dict) -> sqlite3.Connection:
    path = Path(cfg["storage"]["path"]).expanduser()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _latest(conn: sqlite3.Connection, cfg: dict,
            session_id: int | None = None) -> dict:
    # The subquery filter is enough: MAX(id) per name is already scoped
    # to the session, so the outer lookup can only hit those rows.
    w = "WHERE session_id=?" if session_id else ""
    args = (session_id,) if session_id else ()
    obd2: dict[str, float | None] = {}
    units: dict[str, str] = {}
    for row in conn.execute(
            "SELECT name, value, unit FROM obd2 WHERE id IN "
            f"(SELECT MAX(id) FROM obd2 {w} GROUP BY name)", args):
        obd2[row["name"]] = row["value"]
        units[row["name"]] = row["unit"] or ""
    signals: dict[str, dict] = {}
    for row in conn.execute(
            "SELECT signal, value, unit, message FROM signals WHERE id IN "
            f"(SELECT MAX(id) FROM signals {w} GROUP BY signal)", args):
        signals[row["signal"]] = {"value": row["value"],
                                  "unit": row["unit"] or "",
                                  "message": row["message"] or ""}
    ts_row = conn.execute(
        "SELECT MAX(ts) AS ts FROM "
        f"(SELECT ts FROM obd2 {w} UNION ALL SELECT ts FROM signals {w})",
        args + args).fetchone()
    return {"ts": ts_row["ts"] or time.time(),
            "obd2": obd2, "obd2_units": units, "signals": signals,
            "vision": _vision_summary(conn, cfg, session_id)}


def _history(conn: sqlite3.Connection, name: str, limit: int,
             session_id: int | None = None) -> dict:
    limit = max(1, min(limit, 5000))
    filt = "AND session_id=?" if session_id else ""
    args: tuple = (name,) + ((session_id,) if session_id else ())
    rows = conn.execute(
        "SELECT ts, value FROM signals WHERE signal=? " + filt +
        "ORDER BY ts DESC LIMIT ?", args + (limit,)).fetchall()
    table = "signals"
    if not rows:
        rows = conn.execute(
            "SELECT ts, value FROM obd2 WHERE name=? " + filt +
            "ORDER BY ts DESC LIMIT ?", args + (limit,)).fetchall()
        table = "obd2"
    samples = [[r["ts"], r["value"]] for r in reversed(rows)
               if r["value"] is not None]
    return {"signal": name, "table": table, "samples": samples}


def _vision_summary(conn: sqlite3.Connection, cfg: dict,
                    session_id: int | None = None) -> dict:
    """Latest detection per label + recent event count + newest snapshot."""
    w = "WHERE session_id=?" if session_id else ""
    args = (session_id,) if session_id else ()
    w_and = w.replace("WHERE", "AND") if w else ""
    per_label: dict[str, dict] = {}
    for row in conn.execute(
            "SELECT label, confidence, ts FROM vision_events WHERE id IN "
            f"(SELECT MAX(id) FROM vision_events {w} GROUP BY label)", args):
        per_label[row["label"]] = {"confidence": row["confidence"],
                                   "ts": row["ts"]}
    minute_ago = time.time() - 60
    n_recent = conn.execute(
        "SELECT COUNT(*) AS n FROM vision_events "
        f"WHERE ts > ? {w_and}", (minute_ago,) + args).fetchone()["n"]
    snap_row = conn.execute(
        "SELECT snapshot_path FROM vision_events "
        f"WHERE snapshot_path != '' {w_and} ORDER BY ts DESC LIMIT 1",
        args).fetchone()
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


def qs_int(qs: dict, key: str) -> int | None:
    """Optional integer query param, e.g. ?session_id=3."""
    vals = qs.get(key)
    if not vals or not vals[0]:
        return None
    try:
        return int(vals[0])
    except ValueError:
        return None


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
                qs = parse_qs(parsed.query)
                with _connect(self.cfg) as conn:
                    sid = qs_int(qs, "session_id")
                    self._send_json(_latest(conn, self.cfg, sid))
            elif parsed.path == "/api/history":
                qs = parse_qs(parsed.query)
                name = qs.get("signal", [""])[0]
                limit = int(qs.get("limit", ["300"])[0] or 300)
                if not name:
                    self._send_json({"error": "missing ?signal="}, 400)
                    return
                with _connect(self.cfg) as conn:
                    self._send_json(_history(conn, name, limit,
                                             qs_int(qs, "session_id")))
            elif parsed.path == "/api/sessions":
                with _connect(self.cfg) as conn:
                    self._send_json(
                        {"sessions": trip_analytics.list_sessions(conn)})
            elif parsed.path == "/api/trip":
                qs = parse_qs(parsed.query)
                sid = qs_int(qs, "session_id")
                if sid is None:
                    with _connect(self.cfg) as conn:
                        row = conn.execute(
                            "SELECT MAX(id) AS id FROM sessions").fetchone()
                        sid = row["id"] if row else None
                if sid is None:
                    self._send_json({"error": "no sessions yet"}, 404)
                    return
                with _connect(self.cfg) as conn:
                    self._send_json(trip_analytics.summarize(conn, sid))
            elif parsed.path == "/api/track":
                qs = parse_qs(parsed.query)
                sid = qs_int(qs, "session_id")
                if sid is None:
                    self._send_json({"error": "missing ?session_id="}, 400)
                    return
                with _connect(self.cfg) as conn:
                    self._send_json(trip_analytics.track(conn, sid))
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
