"""End-to-end smoke test with no hardware.

Spins up a python-can virtual bus, a fake ECU that answers OBD-II
requests, runs the logger in 'both' mode for a few seconds, then
asserts the SQLite DB actually contains frames and decoded samples.
"""
import sqlite3
import sys
import tempfile
import threading
import time
from pathlib import Path

import can

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from carlogger import logger  # noqa: E402

CHANNEL = "smoke-test-bus"


def fake_ecu(stop: threading.Event):
    """Answer 0x7DF OBD-II requests like a very bored engine."""
    bus = can.interface.Bus(interface="virtual", channel=CHANNEL)
    rpm = 800
    while not stop.is_set():
        msg = bus.recv(timeout=0.05)
        if msg is None or msg.arbitration_id != 0x7DF:
            continue
        data = bytes(msg.data)
        if len(data) < 3 or data[1] != 0x01:
            continue
        pid = data[2]
        rpm = 800 + int(500 * (0.5 + 0.5 * (time.time() % 2)))
        payloads = {
            0x05: [0x03, 0x41, 0x05, 90 + 40],            # coolant 90 C
            0x0C: [0x04, 0x41, 0x0C, (rpm * 4) >> 8 & 0xFF, (rpm * 4) & 0xFF],
            0x0D: [0x03, 0x41, 0x0D, 62],                 # 62 km/h
            0x11: [0x03, 0x41, 0x11, 38],                 # ~15 % throttle
            0x2F: [0x03, 0x41, 0x2F, 178],                # ~70 % fuel
        }
        if pid in payloads:
            raw = payloads[pid] + [0] * (8 - len(payloads[pid]))
            bus.send(can.Message(arbitration_id=0x7E8, data=raw,
                                 is_extended_id=False))
    bus.shutdown()


def chatter(stop: threading.Event):
    """Background CAN traffic like a real bus."""
    bus = can.interface.Bus(interface="virtual", channel=CHANNEL)
    i = 0
    while not stop.is_set():
        bus.send(can.Message(arbitration_id=0x100 + (i % 8),
                             data=[i & 0xFF] * 8, is_extended_id=False))
        i += 1
        time.sleep(0.01)
    bus.shutdown()


def main():
    tmp = Path(tempfile.mkdtemp(prefix="carlogger-smoke-"))
    cfg = {
        "bus": {"interface": "virtual", "channel": CHANNEL},
        "mode": {"mode": "both"},
        "obd2": {"pids": [5, 12, 13, 17, 47],
                 "poll_interval": 0.2, "response_timeout": 0.5},
        "storage": {"path": str(tmp / "drive.db")},
    }
    stop = threading.Event()
    threads = [threading.Thread(target=fake_ecu, args=(stop,)),
               threading.Thread(target=chatter, args=(stop,))]
    for t in threads:
        t.start()
    try:
        db_path = logger.run(cfg, duration=3.0)
    finally:
        stop.set()
        for t in threads:
            t.join()

    conn = sqlite3.connect(db_path)
    n_frames = conn.execute("SELECT COUNT(*) FROM raw_frames").fetchone()[0]
    n_obd = conn.execute("SELECT COUNT(*) FROM obd2").fetchone()[0]
    rows = conn.execute(
        "SELECT pid, name, value, unit FROM obd2 ORDER BY id DESC LIMIT 5"
    ).fetchall()
    conn.close()

    print(f"raw_frames: {n_frames}, obd2 samples: {n_obd}")
    for r in rows:
        print(f"  PID 0x{r[0]:02X} {r[1]} = {r[2]} {r[3]}")
    assert n_frames > 50, "expected background CAN traffic in raw_frames"
    assert n_obd >= 10, "expected decoded OBD-II samples"
    rpm_rows = [r for r in rows if r[0] == 0x0C]
    assert rpm_rows and 700 < rpm_rows[0][2] < 1600, "RPM decode out of range"
    print("SMOKE TEST PASSED")


if __name__ == "__main__":
    main()
