"""toyota-diag command line interface."""

from __future__ import annotations

import argparse
import json
import sys
import time

from . import __version__, decode, prober, protocols


def _list_ports(args) -> int:
    try:
        from serial.tools import list_ports
    except ImportError:
        print("pyserial not installed", file=sys.stderr)
        return 1
    found = False
    for port in list_ports.comports():
        print(f"{port.device:20s} {port.description}")
        found = True
    if not found:
        print("no serial ports found")
    return 0


def _probe(args) -> int:
    names = args.attempt if args.attempt else None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = args.out or f"probe-{stamp}.jsonl"
    print(f"toyota-diag v{__version__}: probing {args.port} @ {args.baud} baud")
    print("Ignition ON (engine can be off for codes, running for live data).")
    records = prober.run_probe(
        port=args.port,
        baud=args.baud,
        attempt_names=names,
        atma_seconds=args.atma_seconds,
        out_path=out,
    )
    print(f"\nwrote {len(records)} exchanges -> {out}\n")
    summary = prober.summarize(records)
    width = max((len(a.name) for a in protocols.PROBE_ATTEMPTS), default=10)
    for attempt in protocols.PROBE_ATTEMPTS:
        if names and attempt.name not in names:
            continue
        entry = summary.get(attempt.name, {"sent": 0, "answered": 0})
        tag = " [experimental]" if attempt.experimental else ""
        print(f"{attempt.name:<{width}}  {entry['answered']:>2}/{entry['sent']:<2} answered{tag}")
        print(f"{' ' * width}  {attempt.description}")
    print("\nSend the .jsonl log for analysis: raw Toyota responses become v0.2 decoders.")
    return 0


def _decode_log(args) -> int:
    with open(args.log, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("phase") not in ("payload", "monitor"):
                continue
            res = decode.summarize_exchange(rec["tx"], rec["rx"])
            print(f"[{rec['attempt']}] {res['tx']} -> {res['rx'][:90]}")
            if res["decoded"]:
                print(f"    decoded: {res['decoded']}")
            if res["note"]:
                print(f"    note: {res['note']}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="toyota-diag",
        description="Free K-Line diagnostic prober for 1990s-2000s JDM Toyotas (v0.1: discovery instrument).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("ports", help="list serial ports").set_defaults(func=_list_ports)

    probe = sub.add_parser("probe", help="probe the car's diagnostic port, log everything")
    probe.add_argument("--port", required=True, help="serial port, e.g. /dev/ttyUSB0 or COM3")
    probe.add_argument("--baud", type=int, default=38400, help="adapter baud rate (default 38400)")
    probe.add_argument(
        "--attempt",
        action="append",
        choices=[a.name for a in protocols.PROBE_ATTEMPTS],
        help="run only this attempt (repeatable); default: all",
    )
    probe.add_argument("--atma-seconds", type=float, default=5.0)
    probe.add_argument("--out", help="JSONL log path (default probe-<timestamp>.jsonl)")
    probe.set_defaults(func=_probe)

    dec = sub.add_parser("decode-log", help="best-effort decode of a probe log")
    dec.add_argument("log", help="JSONL log from a probe run")
    dec.set_defaults(func=_decode_log)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
