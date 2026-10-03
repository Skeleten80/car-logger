#!/usr/bin/env python3
"""Export one drive session to CSV (long format) for analysis in
Excel/pandas.

    python3 tools/export_csv.py --session 3 --out drive3.csv

Columns: ts, source, name, value, unit. sources are obd2, signal and gps
(one row per field, so GPS fixes fan out to lat/lon/alt/speed_kmh/sats
rows). DTC sightings are events, not time series -- see /api/trip or the
dash's trouble-code table for those.
"""
from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from carlogger.config import load_config  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default="config.toml")
    ap.add_argument("--db", default="")
    ap.add_argument("--session", type=int, default=None,
                    help="session id (default: latest)")
    ap.add_argument("--out", default="drive.csv")
    args = ap.parse_args()

    db_path = Path(args.db).expanduser() if args.db else Path(
        load_config(args.config)[0]["storage"]["path"]).expanduser()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    if args.session is None:
        row = conn.execute("SELECT MAX(id) AS id FROM sessions").fetchone()
        sid = row["id"]
        if sid is None:
            print("no sessions in database")
            return 1
    else:
        sid = args.session

    n = 0
    with open(args.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", "source", "name", "value", "unit"])
        for r in conn.execute(
                "SELECT ts, name, value, unit FROM obd2 "
                "WHERE session_id=? ORDER BY ts", (sid,)):
            w.writerow([r["ts"], "obd2", r["name"], r["value"], r["unit"]])
            n += 1
        for r in conn.execute(
                "SELECT ts, signal, value, unit FROM signals "
                "WHERE session_id=? ORDER BY ts", (sid,)):
            w.writerow([r["ts"], "signal", r["signal"], r["value"],
                        r["unit"]])
            n += 1
        for r in conn.execute(
                "SELECT ts, lat, lon, alt, speed_kmh, sats FROM gps_fixes "
                "WHERE session_id=? ORDER BY ts", (sid,)):
            for name, val, unit in (
                    ("lat", r["lat"], "deg"), ("lon", r["lon"], "deg"),
                    ("alt", r["alt"], "m"),
                    ("speed_kmh", r["speed_kmh"], "km/h"),
                    ("sats", r["sats"], "count")):
                if val is not None:
                    w.writerow([r["ts"], "gps", name, val, unit])
                    n += 1
    print(f"session {sid}: {n} rows -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
