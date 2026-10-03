"""Phase-1 vehicle logger.

Reads CAN frames and/or polls OBD-II PIDs, stores everything in SQLite.
Graceful on SIGINT/SIGTERM (what launchd sends at shutdown) so the DB
is always flushed cleanly -- this is what the ignition-off UPS shutdown
relies on.

Usage:
    python -m carlogger.logger [--config config.local.toml] [--duration 60]
"""
from __future__ import annotations

import argparse
import signal
import sys
import time

import can

from .config import load_config
from .db import Store
from .decode import SignalDB
from .obd2 import PIDS, describe_dtc, query, read_dtcs

_stop = False


def _handle_signal(signum, frame):
    global _stop
    _stop = True


def open_bus(cfg: dict) -> can.BusABC:
    b = cfg["bus"]
    kwargs: dict = {"interface": b["interface"], "channel": b["channel"]}
    # virtual bus takes no bitrate; real hardware does
    if b["interface"] != "virtual":
        kwargs["bitrate"] = b.get("bitrate", 500000)
    return can.interface.Bus(**kwargs)


def run(cfg: dict, duration: float | None = None) -> Path:
    global _stop
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    store = Store(cfg["storage"]["path"], note=f"mode={cfg['mode']['mode']}")
    bus = open_bus(cfg)
    mode = cfg["mode"]["mode"]
    pids: list[int] = cfg["obd2"]["pids"]
    poll_interval: float = cfg["obd2"]["poll_interval"]
    resp_timeout: float = cfg["obd2"]["response_timeout"]

    # Phase-2 DBC decoding (optional; empty dbc_path disables it)
    decoder: SignalDB | None = None
    dbc_path = cfg.get("decode", {}).get("dbc_path", "")
    if dbc_path:
        decoder = SignalDB()
        n = decoder.load(dbc_path)
        print(f"DBC decoding on: {n} file(s) from {dbc_path}", flush=True)

    unknown_pids = [p for p in pids if p not in PIDS]
    if unknown_pids:
        print(f"warning: no decoder for PIDs "
              f"{[hex(p) for p in unknown_pids]}, skipping them",
              file=sys.stderr)
        pids = [p for p in pids if p in PIDS]

    do_listen = mode in ("listen", "both")
    do_obd2 = mode in ("obd2", "both")

    print(f"logging mode={mode} -> {store.path} "
          f"(session {store.session_id})", flush=True)
    t_end = time.time() + duration if duration else None
    next_poll = 0.0
    # Periodic DTC check (read-only; clearing is a manual CLI action).
    # 0 disables it. First poll happens after one interval, not at
    # startup, so short runs (and ECU init) aren't starved by the
    # multi-second DTC timeouts.
    dtc_interval = float(cfg["obd2"].get("dtc_poll_interval", 300))
    next_dtc = time.time() + dtc_interval if dtc_interval > 0 else 0.0
    seen_dtcs: set[tuple[str, str]] = set()
    frames = 0
    samples = 0
    sig_samples = 0
    try:
        while not _stop and (t_end is None or time.time() < t_end):
            if do_listen:
                msg = bus.recv(timeout=0.05)
                if msg is not None:
                    ts = msg.timestamp
                    store.log_frame(ts, msg.arbitration_id,
                                    msg.is_extended_id, msg.dlc,
                                    bytes(msg.data))
                    frames += 1
                    if decoder is not None:
                        decoded = decoder.decode(msg.arbitration_id,
                                                 bytes(msg.data),
                                                 msg.is_extended_id)
                        if decoded:
                            store.log_signals(
                                ts, [(m, s, v, u)
                                     for s, (v, u, m) in decoded.items()])
                            sig_samples += len(decoded)
            if do_obd2 and time.time() >= next_poll:
                next_poll = time.time() + poll_interval
                for pid in pids:
                    if _stop:
                        break
                    value, unit = query(bus, pid, timeout=resp_timeout)
                    name = PIDS[pid][0]
                    store.log_obd2(time.time(), pid, name, value, unit)
                    samples += 1
            if (do_obd2 and dtc_interval > 0
                    and time.time() >= next_dtc and not _stop):
                next_dtc = time.time() + dtc_interval
                for pending in (False, True):
                    codes = read_dtcs(bus, pending=pending,
                                      timeout=resp_timeout + 1.0)
                    if not codes:
                        continue
                    status = "pending" if pending else "stored"
                    fresh = [(c, describe_dtc(c), status) for c in codes
                             if (c, status) not in seen_dtcs]
                    if fresh:
                        store.log_dtcs(time.time(), fresh)
                        seen_dtcs.update((c, s) for c, _, s in fresh)
                        print(f"DTCs ({status}): {', '.join(c for c, _, _ in fresh)}",
                              flush=True)
            if not do_listen and do_obd2:
                time.sleep(0.01)  # don't spin when there's nothing to recv
    finally:
        bus.shutdown()
        store.close()
    print(f"done: {frames} frames, {samples} OBD-II samples, "
          f"{sig_samples} DBC signals", flush=True)
    return store.path


def main() -> None:
    ap = argparse.ArgumentParser(description="Phase-1 vehicle logger")
    ap.add_argument("--config", default="config.toml")
    ap.add_argument("--duration", type=float, default=None,
                    help="stop after N seconds (default: run until signal)")
    args = ap.parse_args()

    cfg, cfg_path = load_config(args.config)
    print(f"using config: {cfg_path}", flush=True)
    run(cfg, args.duration)


if __name__ == "__main__":
    main()
