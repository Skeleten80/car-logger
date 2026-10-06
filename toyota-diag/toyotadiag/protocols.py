"""Probe attempts: ordered hypotheses about how to wake the ECU.

v0.1 philosophy: we do NOT assume we know the JDM Toyota protocol. Each
attempt is one hypothesis (an init sequence + a set of payloads). Every
byte the car sends back -- including silence -- is logged by the prober
for later analysis. Payloads flagged ``experimental`` are
community-reported, not verified; treat their results accordingly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple

#: Generic OBD-II payloads tried on every K-Line protocol variant.
GENERIC_PAYLOADS: Tuple[str, ...] = (
    "0100",  # supported PIDs 01-20
    "010C",  # engine RPM
    "010D",  # vehicle speed
    "0105",  # coolant temperature
    "010B",  # intake manifold pressure
    "010F",  # intake air temperature
    "0111",  # throttle position
    "03",    # stored DTCs
    "0902",  # VIN
)

#: Toyota extended mode $21 probes (experimental).
TOYOTA_EXT21_PAYLOADS: Tuple[str, ...] = (
    "2100",  # supported extended PIDs (analogous to 0100)
    "2101",
    "2121",
)


@dataclass(frozen=True)
class Attempt:
    name: str
    description: str
    init: Tuple[str, ...] = ()
    payloads: Tuple[str, ...] = ()
    experimental: bool = False
    #: If True, the single payload is a bus monitor (ATMA) needing a long read.
    monitor: bool = False


PROBE_ATTEMPTS: Tuple[Attempt, ...] = (
    Attempt(
        name="iso9141_5baud",
        description="ISO 9141-2, 5-baud init (ELM327 protocol 3) + generic OBD-II",
        init=("ATSP3",),
        payloads=GENERIC_PAYLOADS,
    ),
    Attempt(
        name="kwp2000_5baud",
        description="ISO 14230-4 KWP2000, 5-baud init (protocol 4) + generic OBD-II",
        init=("ATSP4",),
        payloads=GENERIC_PAYLOADS,
    ),
    Attempt(
        name="kwp2000_fastinit",
        description="ISO 14230-4 KWP2000, fast init (protocol 5) + generic OBD-II",
        init=("ATSP5",),
        payloads=GENERIC_PAYLOADS,
    ),
    Attempt(
        name="toyota_mode21",
        description="Toyota extended mode $21 over K-Line (experimental)",
        init=("ATSP3", "ATH1"),
        payloads=TOYOTA_EXT21_PAYLOADS,
        experimental=True,
    ),
    Attempt(
        name="bus_monitor",
        description="ATMA bus monitor: capture any ECU chatter for 5 s",
        init=("ATSP3",),
        payloads=("ATMA",),
        monitor=True,
        experimental=True,
    ),
)


def get_attempt(name: str) -> Attempt:
    for attempt in PROBE_ATTEMPTS:
        if attempt.name == name:
            return attempt
    raise KeyError(f"unknown probe attempt: {name!r}")
