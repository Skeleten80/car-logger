#!/usr/bin/env python3
"""Seed a demo drive database so the dash (web or CarDash) has lively data
with zero car hardware.

Writes one synthetic session -- ~2 minutes of OBD-II samples, DBC-decoded
signals and vision detections -- into the database the dash server reads
(default: the [storage] path from config.toml). Then run the dash and point
a browser or the CarDash app at it:

    python3 tools/demo_db.py
    python3 -m carlogger.dash

The gauges, strip chart, signal table and vision card all come alive, which
makes this the fastest way to exercise the CarDash UI in Xcode.
"""
from __future__ import annotations

import argparse
import math
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from carlogger.config import load_config  # noqa: E402
from carlogger.db import Store  # noqa: E402
from carlogger.obd2 import describe_dtc  # noqa: E402


def drive_profile(t: float, total: float) -> dict:
    """Return plausible vehicle state at second t of a demo drive."""
    # 0-15s idle, 15-45s accelerate, 45-80s cruise, 80-100s brake to a
    # stop, remainder idle.
    if t < 15:
        speed = 0.0
        rpm = 800.0
        throttle = 0.0
        brake = 0.0
    elif t < 45:
        k = (t - 15) / 30  # 0..1
        speed = 95.0 * k
        # sawtooth "gear shifts" on the way up
        rpm = 800 + 3000 * k + 350 * math.sin(k * math.pi * 6)
        throttle = 65.0 + 10 * math.sin(k * 20)
        brake = 0.0
    elif t < 80:
        speed = 95.0
        rpm = 2400.0
        throttle = 20.0
        brake = 0.0
    elif t < 88:
        # hard stop: 95 -> 0 km/h in 8 s (~-12 km/h/s) to exercise the
        # harsh-braking detector
        k = (t - 80) / 8  # 0..1
        speed = 95.0 * (1 - k)
        rpm = 2400 - 1500 * k
        throttle = 0.0
        brake = 85.0
    else:
        speed = 0.0
        rpm = 850.0
        throttle = 0.0
        brake = 0.0
    steer = 8.0 * math.sin(t * 0.35) if 45 <= t < 80 else 0.0
    return {
        "rpm": max(0.0, rpm + random.uniform(-25, 25)),
        "speed": max(0.0, speed + random.uniform(-1, 1)),
        "throttle": max(0.0, min(100.0, throttle)),
        "brake": brake,
        "steer": steer,
        "coolant": min(95.0, 84.0 + t * 0.09),
        "maf": max(0.0, rpm / 100.0 * (0.8 + throttle / 200.0)),
        "fuel": 62.5 - t * 0.002,
    }


LABELS = ["car", "car", "car", "truck", "traffic light", "person"]


def fake_detections(t: float) -> list[tuple]:
    """One or two plausible YOLO-style detections per vision tick."""
    n = random.choice([1, 1, 2])
    rows = []
    for _ in range(n):
        label = random.choice(LABELS)
        conf = round(random.uniform(0.55, 0.95), 2)
        w = random.uniform(60, 220)
        h = random.uniform(50, 180)
        x1 = round(random.uniform(0, 640 - w), 1)
        y1 = round(random.uniform(60, 480 - h), 1)
        interesting = label == "person" and conf > 0.7
        rows.append((label, conf, x1, y1, round(x1 + w, 1),
                     round(y1 + h, 1), "", interesting))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default="config.toml",
                    help="config file (used for the [storage] db path)")
    ap.add_argument("--db", default="",
                    help="override the database path")
    ap.add_argument("--seconds", type=float, default=120,
                    help="length of the fake drive in seconds")
    ap.add_argument("--hz", type=float, default=2.0,
                    help="sample rate for OBD-II/signals")
    ap.add_argument("--seed", type=int, default=7,
                    help="random seed (same seed = same drive)")
    args = ap.parse_args()

def seed_db(db_path: Path, seconds: float = 120, hz: float = 2.0,
            seed: int = 7) -> int:
    """Seed one fake drive; returns the session id. Importable so tests
    can build deterministic fixtures (same seed = same drive)."""
    random.seed(seed)
    store = Store(db_path, note="mode=demo")
    t0 = time.time() - seconds
    dt = 1.0 / hz
    steps = int(seconds / dt)
    n_vis = 0
    # Fake GPS: start near Stratford ON, heading north, gentle curve
    # while cruising so the track looks like a real road.
    lat, lon, heading = 43.3680, -80.9820, 0.0
    n_gps = 0
    for i in range(steps):
        t = i * dt
        ts = t0 + t
        s = drive_profile(t, seconds)

        for pid, name, val, unit in (
                (12, "rpm", s["rpm"], "rpm"),
                (13, "speed", s["speed"], "km/h"),
                (5, "coolant_temp", s["coolant"], "degC"),
                (16, "maf", s["maf"], "g/s"),
                (17, "throttle", s["throttle"], "%"),
                (47, "fuel_level", s["fuel"], "%")):
            store.log_obd2(ts, pid, name, round(val, 2), unit)

        store.log_signals(ts, [
            ("ENGINE", "EngineRPM", round(s["rpm"], 1), "rpm"),
            ("ENGINE", "VehicleSpeed", round(s["speed"], 1), "km/h"),
            ("ENGINE", "CoolantTemp", round(s["coolant"], 1), "degC"),
            ("ENGINE", "ThrottlePos", round(s["throttle"], 1), "%"),
            ("STEERING", "SteeringAngle", round(s["steer"], 1), "deg"),
            ("BRAKE", "BrakePedal", round(s["brake"], 1), "%"),
        ])

        # GPS fix at 1 Hz while moving (receivers drop out at standstill
        # in parking garages; this keeps the demo honest-ish).
        if i % int(hz) == 0 and s["speed"] > 3:
            if 45 <= t < 80:
                heading += 0.35  # gentle right curve on the cruise leg
            dist_m = s["speed"] / 3.6 * 1.0
            lat += dist_m * math.cos(math.radians(heading)) / 111320.0
            lon += (dist_m * math.sin(math.radians(heading))
                    / (111320.0 * math.cos(math.radians(lat))))
            store.log_gps(ts, round(lat, 6), round(lon, 6),
                          alt=round(345 + 4 * math.sin(t * 0.05), 1),
                          speed_kmh=round(s["speed"], 1), sats=8)
            n_gps += 1

        # vision tick at 1 Hz
        if i % int(hz) == 0:
            rows = fake_detections(t)
            store.log_vision(ts, rows)
            n_vis += len(rows)

    # a stored misfire code mid-drive and a pending catalyst code later
    t_mid = t0 + seconds * 0.4
    store.log_dtcs(t_mid, [("P0300", describe_dtc("P0300"), "stored")])
    store.log_dtcs(t0 + seconds * 0.7,
                   [("P0420", describe_dtc("P0420"), "pending")])
    store.close()
    print(f"seeded session {store.session_id} -> {db_path}")
    print(f"  {steps * 6} OBD-II samples, {steps * 6} signal samples, "
          f"{n_vis} vision events, {n_gps} GPS fixes, 2 DTCs")
    return store.session_id


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default="config.toml",
                    help="config file (used for the [storage] db path)")
    ap.add_argument("--db", default="",
                    help="override the database path")
    ap.add_argument("--seconds", type=float, default=120,
                    help="length of the fake drive in seconds")
    ap.add_argument("--hz", type=float, default=2.0,
                    help="sample rate for OBD-II/signals")
    ap.add_argument("--seed", type=int, default=7,
                    help="random seed (same seed = same drive)")
    args = ap.parse_args()

    if args.db:
        db_path = Path(args.db).expanduser()
    else:
        cfg, _ = load_config(args.config)
        db_path = Path(cfg["storage"]["path"]).expanduser()

    seed_db(db_path, args.seconds, args.hz, args.seed)
    print("serve it with:  python3 -m carlogger.dash")
    return 0


if __name__ == "__main__":
    sys.exit(main())
