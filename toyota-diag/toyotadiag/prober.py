"""Probe runner: tries each protocol attempt, logs every exchange as JSONL.

Nothing here interprets Toyota-proprietary bytes -- v0.1 records them so
decoding tables can be built from real logs (see README roadmap).
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass

from . import protocols
from .elm327 import ELM327, ELM327Error

#: Adapter setup run once before any attempt.
SESSION_SETUP = ("ATE0", "ATL0", "ATH1", "ATRV")


@dataclass
class Record:
    ts: float
    attempt: str
    phase: str  # "session" | "init" | "payload" | "monitor"
    tx: str
    rx: str

    def to_json(self) -> str:
        return json.dumps(asdict(self))


def _safe_command(elm: ELM327, cmd: str, extra_timeout: float = 0.0) -> str:
    try:
        return elm.command(cmd, extra_timeout=extra_timeout)
    except ELM327Error as exc:
        return f"<adapter-error: {exc}>"


def run_probe(
    port: str,
    baud: int = 38400,
    attempt_names: "list[str] | None" = None,
    atma_seconds: float = 5.0,
    out_path: "str | None" = None,
    serial_factory=None,
) -> list[Record]:
    """Run probe attempts; return records and optionally append them to JSONL."""
    if attempt_names is None:
        attempt_names = [a.name for a in protocols.PROBE_ATTEMPTS]
    attempts = [protocols.get_attempt(n) for n in attempt_names]

    records: list[Record] = []

    def log(attempt: str, phase: str, tx: str, rx: str) -> None:
        records.append(Record(ts=time.time(), attempt=attempt, phase=phase, tx=tx, rx=rx))

    with ELM327(port, baud=baud, serial_factory=serial_factory) as elm:
        log("session", "session", "ATZ", _safe_command(elm, "ATZ", extra_timeout=2.0))
        for cmd in SESSION_SETUP:
            log("session", "session", cmd, _safe_command(elm, cmd))
        for attempt in attempts:
            for cmd in attempt.init:
                log(attempt.name, "init", cmd, _safe_command(elm, cmd))
            for payload in attempt.payloads:
                if attempt.monitor:
                    rx = _safe_command(elm, payload, extra_timeout=atma_seconds)
                    log(attempt.name, "monitor", payload, rx)
                else:
                    log(attempt.name, "payload", payload, _safe_command(elm, payload))

    if out_path:
        with open(out_path, "a", encoding="utf-8") as fh:
            for record in records:
                fh.write(record.to_json() + "\n")
    return records


def summarize(records: list[Record]) -> dict:
    """Per-attempt hit count: payloads that got *any* ECU-ish response."""
    noisy = ("NO DATA", "?", "UNABLE TO CONNECT", "<adapter-error", "SEARCHING")
    summary: dict = {}
    for record in records:
        if record.phase not in ("payload", "monitor"):
            continue
        entry = summary.setdefault(record.attempt, {"sent": 0, "answered": 0})
        entry["sent"] += 1
        rx = record.rx.upper()
        if rx and not any(token in rx for token in noisy):
            entry["answered"] += 1
    return summary
