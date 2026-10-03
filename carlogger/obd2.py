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


# ---------------------------------------------------------------------------
# Diagnostic Trouble Codes (modes 0x03 stored / 0x07 pending, 0x04 clear)
#
# A DTC is two bytes: the top two bits of the first byte select the family
# (00=P powertrain, 01=C chassis, 10=B body, 11=U network), the rest is
# BCD-ish: e.g. bytes 0x03 0x00 -> P0300 (random/multiple misfire).
# Responses longer than one CAN frame use ISO-TP: first frame (0x1N) gives
# the total length, we answer with a flow-control frame (0x30), then the
# ECU streams consecutive frames (0x2N).

def decode_dtc(b1: int, b2: int) -> str:
    """Decode two raw bytes into a code like 'P0300'."""
    family = "PCBU"[(b1 >> 6) & 0x03]
    return (f"{family}{(b1 >> 4) & 0x03:X}{b1 & 0x0F:X}"
            f"{(b2 >> 4) & 0x0F:X}{b2 & 0x0F:X}")


def _isotp_request(bus: can.BusABC, service: int,
                   timeout: float = 1.0) -> bytes | None:
    """Send a service request and reassemble the ISO-TP response payload.

    Returns the payload bytes *after* the PCI framing (starting with the
    service response byte), or None on timeout / malformed reply.
    """
    bus.send(can.Message(
        arbitration_id=REQUEST_ID,
        data=[0x02, service, 0x00, 0, 0, 0, 0, 0],
        is_extended_id=False))
    deadline = time.time() + timeout
    payload = bytearray()
    total_len: int | None = None
    next_seq = 1
    fc_sent = False
    while time.time() < deadline:
        msg = bus.recv(max(0.0, deadline - time.time()))
        if msg is None:
            continue
        data = bytes(msg.data)
        if msg.arbitration_id not in RESPONSE_IDS or not data:
            continue
        pci = data[0]
        frame_type = pci & 0xF0
        if frame_type == 0x00 and total_len is None:  # single frame
            length = pci & 0x0F
            return bytes(data[1:1 + length])
        if frame_type == 0x10 and total_len is None:  # first frame
            total_len = ((pci & 0x0F) << 8) | data[1]
            payload += data[2:8]
        elif frame_type == 0x20 and total_len is not None:  # consecutive
            if (pci & 0x0F) != (next_seq & 0x0F):
                return None  # sequence break; give up
            next_seq += 1
            payload += data[1:8]
        else:
            continue
        if total_len is not None and not fc_sent:
            bus.send(can.Message(
                arbitration_id=REQUEST_ID,
                data=[0x30, 0x00, 0x00, 0, 0, 0, 0, 0],
                is_extended_id=False))
            fc_sent = True
        if total_len is not None and len(payload) >= total_len:
            return bytes(payload[:total_len])
    return None


def read_dtcs(bus: can.BusABC, pending: bool = False,
              timeout: float = 2.0) -> list[str] | None:
    """Read DTCs (mode 0x03 stored, 0x07 pending).

    Returns a list of code strings (possibly empty), or None if the ECU
    didn't answer at all.
    """
    service = 0x07 if pending else 0x03
    payload = _isotp_request(bus, service, timeout)
    if payload is None or len(payload) < 2:
        return None
    if payload[0] != service + 0x40:
        return None
    count = payload[1]
    codes = []
    for i in range(count):
        o = 2 + 2 * i
        if o + 1 >= len(payload):
            break
        b1, b2 = payload[o], payload[o + 1]
        if b1 == 0 and b2 == 0:
            continue  # padding
        codes.append(decode_dtc(b1, b2))
    return codes


def clear_dtcs(bus: can.BusABC, timeout: float = 2.0) -> bool:
    """Clear stored DTCs + freeze frames (mode 0x04). Returns True on
    positive response. Manual use only -- the logger never calls this."""
    payload = _isotp_request(bus, 0x04, timeout)
    return payload is not None and len(payload) >= 1 and payload[0] == 0x44


# Common generic (P0xxx) code descriptions. Anything not listed shows the
# raw code in the dash -- this table is a convenience, not exhaustive.
DTC_DESCRIPTIONS: dict[str, str] = {
    "P0000": "No fault detected",
    "P0101": "Mass air flow sensor range/performance",
    "P0102": "Mass air flow sensor low input",
    "P0113": "Intake air temperature sensor high input",
    "P0128": "Coolant thermostat (coolant temp below regulating temp)",
    "P0171": "System too lean (bank 1)",
    "P0172": "System too rich (bank 1)",
    "P0174": "System too lean (bank 2)",
    "P0300": "Random/multiple cylinder misfire detected",
    "P0301": "Cylinder 1 misfire detected",
    "P0302": "Cylinder 2 misfire detected",
    "P0303": "Cylinder 3 misfire detected",
    "P0304": "Cylinder 4 misfire detected",
    "P0305": "Cylinder 5 misfire detected",
    "P0306": "Cylinder 6 misfire detected",
    "P0335": "Crankshaft position sensor circuit",
    "P0340": "Camshaft position sensor circuit",
    "P0401": "Exhaust gas recirculation flow insufficient",
    "P0420": "Catalyst system efficiency below threshold (bank 1)",
    "P0430": "Catalyst system efficiency below threshold (bank 2)",
    "P0440": "Evaporative emission system malfunction",
    "P0442": "Evaporative emission system leak (small)",
    "P0455": "Evaporative emission system leak (large)",
    "P0500": "Vehicle speed sensor malfunction",
    "P0507": "Idle air control RPM higher than expected",
    "P0562": "System voltage low",
    "P0606": "ECM/PCM processor fault",
    "P0700": "Transmission control system malfunction",
    "P0715": "Input/turbine speed sensor circuit",
    "P0730": "Incorrect gear ratio",
    "P0740": "Torque converter clutch circuit malfunction",
    "P0750": "Shift solenoid A malfunction",
    "P0780": "Shift malfunction",
    "P0A80": "Replace hybrid battery pack",
    "P0A7F": "Hybrid battery pack deterioration",
}


def describe_dtc(code: str) -> str:
    """Human-readable description for a DTC, or '' if unknown."""
    return DTC_DESCRIPTIONS.get(code.upper(), "")


def _open_default_bus() -> can.BusABC:
    from .config import load_config
    from .logger import open_bus
    cfg, _ = load_config("config.toml")
    return open_bus(cfg)


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(
        description="Read (or clear) diagnostic trouble codes")
    ap.add_argument("--pending", action="store_true",
                    help="read pending codes (mode 0x07) instead of stored")
    ap.add_argument("--clear", action="store_true",
                    help="clear codes (mode 0x04)")
    ap.add_argument("--confirm", action="store_true",
                    help="required together with --clear")
    args = ap.parse_args()
    bus = _open_default_bus()
    try:
        if args.clear:
            if not args.confirm:
                print("refusing to clear without --confirm "
                      "(this erases freeze-frame data too)")
                return
            print("clearing DTCs...", flush=True)
            print("OK" if clear_dtcs(bus) else "no response from ECU")
            return
        codes = read_dtcs(bus, pending=args.pending)
        if codes is None:
            print("no response from ECU")
        elif not codes:
            print("no DTCs reported")
        else:
            for c in codes:
                desc = describe_dtc(c)
                print(f"{c}  {desc}" if desc else c)
    finally:
        bus.shutdown()


if __name__ == "__main__":
    main()
