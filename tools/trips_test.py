#!/usr/bin/env python3
"""Tests for the six new car-logger features: DTC read/decode (modes
03/07/04 incl. ISO-TP multi-frame), NMEA GPS parsing, trip analytics,
/api/sessions + /api/trip + /api/track, and CSV export.

Hardware-dependent paths (real ECU answers, real GPS serial) are not
covered here -- the fake ECU below stands in for the car.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import can

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from carlogger import dash, logger, trips  # noqa: E402
from carlogger.dash import create_server  # noqa: E402
from carlogger.gps import nmea_checksum_ok, parse_nmea  # noqa: E402
from carlogger.obd2 import (clear_dtcs, decode_dtc, describe_dtc,  # noqa: E402
                            read_dtcs)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from demo_db import seed_db  # noqa: E402

CHANNEL = "tcan-dtc"

# P0300, P0420
DTC_2CODES = [0x06, 0x43, 0x02, 0x03, 0x00, 0x04, 0x20, 0x00]
# P0171 pending
DTC_PENDING = [0x04, 0x47, 0x01, 0x01, 0x71, 0x00, 0x00, 0x00]
# 4 codes -> must use ISO-TP multi-frame: P0300 P0420 P0171 U0100
MF_CODES = [(0x03, 0x00), (0x04, 0x20), (0x01, 0x71), (0xC1, 0x00)]


def fake_ecu(stop: threading.Event, multiframe: bool = False,
             ready: threading.Event | None = None):
    bus = can.interface.Bus(interface="virtual", channel=CHANNEL)
    if ready is not None:
        ready.set()
    while not stop.is_set():
        msg = bus.recv(timeout=0.05)
        if msg is None or msg.arbitration_id != 0x7DF:
            continue
        data = bytes(msg.data)
        if len(data) < 2:
            continue
        if data[0] == 0x30:
            continue  # flow control for our own multi-frame reply
        service = data[1]
        if service == 0x03 and not multiframe:
            bus.send(can.Message(arbitration_id=0x7E8, data=DTC_2CODES,
                                 is_extended_id=False))
        elif service == 0x07 and not multiframe:
            bus.send(can.Message(arbitration_id=0x7E8, data=DTC_PENDING,
                                 is_extended_id=False))
        elif service == 0x03 and multiframe:
            payload = [0x43, 0x04] + [b for c in MF_CODES for b in c]
            total = len(payload)
            first = [0x10 | (total >> 8), total & 0xFF] + payload[:6]
            bus.send(can.Message(arbitration_id=0x7E8, data=first,
                                 is_extended_id=False))
            # wait for the client's flow-control frame
            deadline = time.time() + 2.0
            while time.time() < deadline:
                fc = bus.recv(timeout=0.1)
                if (fc is not None and fc.arbitration_id == 0x7DF
                        and bytes(fc.data)[0] == 0x30):
                    break
            rest = payload[6:]
            chunk = [0x21] + rest + [0] * (7 - len(rest))
            bus.send(can.Message(arbitration_id=0x7E8, data=chunk,
                                 is_extended_id=False))
        elif service == 0x04:
            bus.send(can.Message(
                arbitration_id=0x7E8,
                data=[0x01, 0x44, 0, 0, 0, 0, 0, 0],
                is_extended_id=False))
    bus.shutdown()


def check(cond: bool, label: str) -> None:
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        raise SystemExit(f"FAILED: {label}")


def nmea_with(body: str) -> str:
    cs = 0
    for ch in body:
        cs ^= ord(ch)
    return f"${body}*{cs:02X}"


def main() -> None:
    # --- DTC decode unit checks ---
    check(decode_dtc(0x03, 0x00) == "P0300", "decode P0300")
    check(decode_dtc(0x04, 0x20) == "P0420", "decode P0420")
    check(decode_dtc(0xC1, 0x00) == "U0100", "decode U0100 (network family)")
    check(decode_dtc(0x01, 0x71) == "P0171", "decode P0171")
    check(describe_dtc("P0300").startswith("Random/multiple"),
          "P0300 description")
    check(describe_dtc("P9999") == "", "unknown code -> empty description")

    # --- DTC over virtual CAN ---
    stop = threading.Event()
    ready = threading.Event()
    t = threading.Thread(target=fake_ecu, args=(stop, False, ready),
                         daemon=True)
    t.start()
    ready.wait(timeout=5)
    bus = can.interface.Bus(interface="virtual", channel=CHANNEL)
    try:
        check(read_dtcs(bus) == ["P0300", "P0420"], "mode 03 stored codes")
        check(read_dtcs(bus, pending=True) == ["P0171"],
              "mode 07 pending codes")
        check(clear_dtcs(bus) is True, "mode 04 clear positive response")
    finally:
        stop.set()
        t.join()
        bus.shutdown()

    stop = threading.Event()
    ready = threading.Event()
    t = threading.Thread(target=fake_ecu, args=(stop, True, ready),
                         daemon=True)
    t.start()
    ready.wait(timeout=5)
    bus = can.interface.Bus(interface="virtual", channel=CHANNEL)
    try:
        check(read_dtcs(bus) == ["P0300", "P0420", "P0171", "U0100"],
              "ISO-TP multi-frame reassembly (4 codes)")
    finally:
        stop.set()
        t.join()
        bus.shutdown()

    # --- logger's periodic DTC poll, end to end ---
    def ecu_pid_and_dtc(stop: threading.Event, ready: threading.Event):
        bus = can.interface.Bus(interface="virtual", channel="tcan-logdtc")
        ready.set()
        while not stop.is_set():
            msg = bus.recv(timeout=0.05)
            if msg is None or msg.arbitration_id != 0x7DF:
                continue
            data = bytes(msg.data)
            if len(data) < 3:
                continue
            if data[1] == 0x01 and data[2] == 0x0C:
                bus.send(can.Message(
                    arbitration_id=0x7E8,
                    data=[0x04, 0x41, 0x0C, 0x1F, 0x40, 0, 0, 0],
                    is_extended_id=False))
            elif data[1] == 0x03:
                bus.send(can.Message(
                    arbitration_id=0x7E8,
                    data=[0x04, 0x43, 0x01, 0x03, 0x00, 0, 0, 0],
                    is_extended_id=False))
        bus.shutdown()

    with tempfile.TemporaryDirectory() as td:
        db = str(Path(td) / "dtc.db")
        stop = threading.Event()
        ready = threading.Event()
        t = threading.Thread(target=ecu_pid_and_dtc, args=(stop, ready),
                             daemon=True)
        t.start()
        ready.wait(timeout=5)
        cfg = {
            "bus": {"interface": "virtual", "channel": "tcan-logdtc"},
            "mode": {"mode": "obd2"},
            "obd2": {"pids": [12], "poll_interval": 0.5,
                     "response_timeout": 0.5, "dtc_poll_interval": 1.5},
            "storage": {"path": db},
            "decode": {"dbc_path": ""},
        }
        try:
            logger.run(cfg, duration=5.0)
        finally:
            stop.set()
            t.join()
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT code, description, status FROM dtc_events").fetchall()
        check(len(rows) == 1 and rows[0]["code"] == "P0300"
              and rows[0]["status"] == "stored",
              "logger polls + logs DTCs each session (deduped)")
        check(rows[0]["description"].startswith("Random/multiple"),
              "logged DTC carries description")
        n_obd = conn.execute("SELECT COUNT(*) AS n FROM obd2").fetchone()["n"]
        check(n_obd > 3, "OBD-II polling unaffected by DTC polls")
        conn.close()

    # --- NMEA parsing ---
    rmc = "$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A"
    gga = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47"
    check(nmea_checksum_ok(rmc) and nmea_checksum_ok(gga),
          "canonical NMEA checksums verify")
    f = parse_nmea(rmc)
    check(f is not None and abs(f["lat"] - 48.1173) < 1e-4
          and abs(f["lon"] - 11.5167) < 1e-4, "RMC lat/lon")
    check(f is not None and abs(f["speed_kmh"] - 22.4 * 1.852) < 0.01,
          "RMC knots -> km/h")
    g = parse_nmea(gga)
    check(g is not None and abs(g["alt_m"] - 545.4) < 0.01 and g["sats"] == 8,
          "GGA altitude + satellites")
    check(parse_nmea(rmc[:-2] + "00") is None, "bad checksum rejected")
    check(parse_nmea(nmea_with(
        "GPRMC,123519,V,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W,"))
        is None, "void RMC fix rejected")
    check(parse_nmea("$GPGSV,1,1,01,02,45,123,40*7F") is None,
          "non-position sentence ignored")

    # --- seeded drive -> trip analytics ---
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "drive.db"
        sid = seed_db(db, seconds=120, hz=2.0, seed=7)
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row

        sessions = trips.list_sessions(conn)
        check(len(sessions) == 1 and sessions[0]["id"] == sid,
              "list_sessions finds the seeded drive")
        check(sessions[0]["counts"]["gps_fixes"] > 20,
              "session counts include GPS fixes")

        sm = trips.summarize(conn, sid)
        check(0.5 < (sm["distance_km"] or 0) < 5, "trip distance sane")
        check(abs((sm["duration_s"] or 0) - 119) < 3, "trip duration ~120s")
        check(sm["max_speed_kmh"] is not None and sm["max_speed_kmh"] > 80,
              "top speed captured")
        check(5 < (sm["l_per_100km"] or 0) < 25, "fuel economy sane")
        check((sm["harsh_brake_events"] or 0) >= 1, "harsh braking detected")
        check(sm["dtc_count"] == 2, "both seeded DTCs in summary")
        codes = {d["code"]: d["status"] for d in sm["dtcs"]}
        check(codes == {"P0300": "stored", "P0420": "pending"},
              "DTC codes + statuses")
        check(sm["dtcs"][0]["description"].startswith("Random/multiple"),
              "DTC description carried through")
        check((sm["gps_fixes"] or 0) > 20, "GPS fixes in summary")
        check(sm["gps_bbox"] is not None and
              sm["gps_bbox"][0] < sm["gps_bbox"][2], "GPS bbox sane")
        check((sm["vision_interesting"] or 0) > 0, "interesting frames")

        tr = trips.track(conn, sid)
        check(len(tr["points"]) > 20, "GPS track points")
        la, lo = tr["points"][0]
        check(43 < la < 44 and -81 < lo < -80, "track near Stratford ON")

        check(trips.summarize(conn, 999).get("error"),
              "unknown session -> error dict")

        # --- dash API on the seeded DB ---
        cfg = {"storage": {"path": str(db)}, "dash": {"host": "127.0.0.1",
                                                      "port": 18099}}
        server = create_server(cfg)
        st = threading.Thread(target=server.serve_forever, daemon=True)
        st.start()
        time.sleep(0.3)
        try:
            def get(path):
                with urllib.request.urlopen(
                        f"http://127.0.0.1:18099{path}") as r:
                    return json.load(r)

            ss = get("/api/sessions")
            check(len(ss["sessions"]) == 1, "/api/sessions")
            tp = get(f"/api/trip?session_id={sid}")
            check(tp["distance_km"] == sm["distance_km"], "/api/trip")
            tp2 = get("/api/trip")
            check(tp2["session_id"] == sid, "/api/trip defaults to latest")
            tk = get(f"/api/track?session_id={sid}")
            check(len(tk["points"]) > 20, "/api/track")
            lt = get(f"/api/latest?session_id={sid}")
            check("rpm" in lt["obd2"], "/api/latest?session_id=")
            lt2 = get("/api/latest")
            check("rpm" in lt2["obd2"], "/api/latest unfiltered still works")
            h = get("/api/history?signal=rpm&limit=50&session_id=1")
            check(len(h["samples"]) == 50, "/api/history?session_id=")
        finally:
            server.shutdown()

        # --- CSV export ---
        out = Path(td) / "drive.csv"
        r = subprocess.run(
            [sys.executable, "tools/export_csv.py", "--db", str(db),
             "--session", str(sid), "--out", str(out)],
            capture_output=True, text=True, cwd=Path(__file__).parent.parent)
        check(r.returncode == 0, f"export_csv runs: {r.stderr.strip()[-200:]}")
        rows = out.read_text().splitlines()
        check(rows[0] == "ts,source,name,value,unit", "CSV header")
        sources = {row.split(",")[1] for row in rows[1:]}
        check({"obd2", "signal", "gps"} <= sources, "CSV has all sources")
        check(len(rows) > 1000, f"CSV row count ({len(rows)})")

    print("TRIPS TEST PASSED")


if __name__ == "__main__":
    main()
