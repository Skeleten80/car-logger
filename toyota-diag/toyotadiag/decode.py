"""Minimal decoders for generic OBD-II responses (v0.1).

Generic mode $01/$03/$09 responses are decoded where the formulas are
standard (SAE J1979). Toyota-proprietary responses (mode $21 and friends)
are passed through RAW in v0.1 -- decoding tables get built from real
probe logs, see README roadmap.
"""

from __future__ import annotations


def _hex_bytes(text: str) -> bytes:
    cleaned = "".join(text.split())
    if len(cleaned) % 2:
        return b""
    try:
        return bytes.fromhex(cleaned)
    except ValueError:
        return b""


def _find_payload(frame: bytes, mode: int, pid: int | None = None) -> bytes | None:
    """Locate a positive response (mode+0x40, optional PID echo) in a frame."""
    want = bytes([mode + 0x40] + ([pid] if pid is not None else []))
    idx = frame.find(want)
    if idx < 0:
        return None
    return frame[idx + len(want):]


def decode_mode01_pid(pid: int, data: bytes) -> dict:
    """Decode a few standard PIDs. Unknown PIDs return raw bytes."""
    if pid == 0x00 and len(data) >= 4:
        supported = []
        bits = int.from_bytes(data[:4], "big")
        for i in range(1, 33):
            if bits & (1 << (32 - i)):
                supported.append(f"{i:02X}")
        return {"supported_pids_01_20": supported}
    if pid == 0x04 and data:
        return {"engine_load_pct": round(data[0] * 100 / 255, 1)}
    if pid == 0x05 and data:
        return {"coolant_temp_c": data[0] - 40}
    if pid == 0x0B and data:
        return {"map_kpa": data[0]}
    if pid == 0x0C and len(data) >= 2:
        return {"rpm": ((data[0] << 8) | data[1]) / 4}
    if pid == 0x0D and data:
        return {"speed_kmh": data[0]}
    if pid == 0x0F and data:
        return {"iat_temp_c": data[0] - 40}
    if pid == 0x11 and data:
        return {"throttle_pct": round(data[0] * 100 / 255, 1)}
    return {"raw": data.hex(" ").upper()}


def decode_dtcs(data: bytes) -> list[str]:
    """Decode a mode $03 payload into ['P0133', ...]."""
    codes = []
    for i in range(0, len(data) - 1, 2):
        a, b = data[i], data[i + 1]
        if a == 0 and b == 0:
            continue
        first = "PCBU"[(a >> 6) & 0x03]
        codes.append(f"{first}{a >> 4 & 0x03}{a & 0x0F:X}{(b >> 4):X}{b & 0x0F:X}")
    return codes


def summarize_exchange(tx: str, rx: str) -> dict:
    """Best-effort decode of one probe exchange. Never raises."""
    out: dict = {"tx": tx, "rx": rx, "decoded": None, "note": ""}
    try:
        frame = _hex_bytes(rx)
        if not frame:
            out["note"] = "no hex data in response"
            return out
        tx_b = _hex_bytes(tx)
        if len(tx_b) == 2 and tx_b[0] == 0x01:  # mode 01 + PID
            payload = _find_payload(frame, 0x01, tx_b[1])
            if payload is not None:
                out["decoded"] = decode_mode01_pid(tx_b[1], payload)
                return out
        if tx.strip() == "03":
            payload = _find_payload(frame, 0x03)
            if payload is not None:
                out["decoded"] = {"dtcs": decode_dtcs(payload)}
                return out
        if len(tx_b) == 2 and tx_b[0] == 0x21:  # Toyota extended
            payload = _find_payload(frame, 0x21, tx_b[1])
            if payload is not None:
                out["decoded"] = {"toyota_ext21_raw": payload.hex(" ").upper()}
                out["note"] = "Toyota proprietary payload: captured raw (v0.1 does not decode)"
                return out
        out["note"] = "unrecognized response format; captured raw"
    except Exception as exc:  # never let a decoder kill a probe session
        out["note"] = f"decoder error (non-fatal): {exc}"
    return out
