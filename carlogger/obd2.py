"""Minimal OBD-II (SAE J1979) client over CAN.

Request:  ID 0x7DF, data [0x02, 0x01, <pid>, 0,0,0,0,0]
Response: ID 0x7E8..0x7EF, data [len, 0x41, <pid>, A, B, C, D, ...]

Only the PIDs in PIDS below are decoded; add more from the J1979 table
as needed (each entry is name, unit, and a decoder over bytes A..D).
"""
from __future__ import annotations

import time
from typing import Callable

import can

REQUEST_ID = 0x7DF
RESPONSE_IDS = frozenset(range(0x7E8, 0x7F0))

Decoder = Callable[[int, int, int, int], float]

PIDS: dict[int, tuple[str, str, Decoder]] = {
    0x05: ("coolant_temp", "degC", lambda a, b, c, d: a - 40),
    0x0C: ("rpm", "rpm", lambda a, b, c, d: ((a * 256) + b) / 4),
    0x0D: ("speed", "km/h", lambda a, b, c, d: a),
    0x10: ("maf", "g/s", lambda a, b, c, d: ((a * 256) + b) / 100),
    0x11: ("throttle", "%", lambda a, b, c, d: a * 100 / 255),
    0x2F: ("fuel_level", "%", lambda a, b, c, d: a * 100 / 255),
}


def query(bus: can.BusABC, pid: int,
          timeout: float = 1.0) -> tuple[float | None, str]:
    """Request one PID; returns (value, unit) or (None, "") on timeout."""
    if pid not in PIDS:
        raise ValueError(f"PID 0x{pid:02X} not in decode table")
    name, unit, decode = PIDS[pid]
    req = can.Message(
        arbitration_id=REQUEST_ID,
        data=[0x02, 0x01, pid, 0, 0, 0, 0, 0],
        is_extended_id=False,
    )
    bus.send(req)
    deadline = time.time() + timeout
    while time.time() < deadline:
        msg = bus.recv(max(0.0, deadline - time.time()))
        if msg is None:
            continue
        data = bytes(msg.data)
        if (msg.arbitration_id in RESPONSE_IDS and len(data) >= 3
                and data[1] == 0x41 and data[2] == pid):
            payload = list(data[3:7]) + [0] * 4
            return decode(*payload[:4]), unit
    return None, ""
