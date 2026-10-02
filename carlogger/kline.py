"""ELM327 K-Line OBD-II poller for the Aristo V300 (JZS161).

The JZS161 does NOT have CAN on its diagnostic port -- the engine ECU speaks
ISO 9141-2 K-Line on DLC3 pin 7. This module polls SAE J1979 PIDs through a
USB ELM327 adapter using python-OBD and writes the samples into the same
`obd2` SQLite table as carlogger/obd2.py, so the web dash and CarDash work
unchanged.

Read-only by design: only Mode 01/03 diagnostic requests are ever sent.
No CAN transmit, no writes to the vehicle -- the phase-1 safety rule holds.

What couldn't be verified without the car (see
vehicles/aristo-v300/profile.yaml):
- ELM327 init timing on this K-Line (5-baud vs fast init). We try 5-baud
  init first (fast=False) because old Toyota K-Lines prefer it, fall back
  to fast init once, then fail loudly with an actionable message.
- Real per-PID latency. The poll plan's 5 Hz fast / 1 Hz slow split is a
  starting point -- re-tune after verification step 5.

Usage:
    python -m carlogger.kline --port /dev/cu.usbserial-XXXX [--interval 1.0]
    python -m carlogger.kline --dry-run --duration 10   # no hardware needed
"""
from __future__ import annotations

import argparse
import math
import signal
import time
from pathlib import Path

try:
    import obd
except ImportError:  # handled with a clear message at connect time
    obd = None

import yaml

from .db import Store

# Package root: carlogger/.. (so vehicles/aristo-v300/profile.yaml resolves
# no matter where the process is started from).
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROFILE = ROOT / "vehicles" / "aristo-v300" / "profile.yaml"
DEFAULT_DB = "~/car-logger-data/drive.db"

# ELM327 protocol "3" == ISO 9141-2, per profile.yaml diagnostics.transport.
KLINE_PROTOCOL = "3"
KLINE_BAUDRATE = 10400

# Profile PID name -> python-OBD built-in command attribute.
# Mapped from the profile's PID hex codes; python-OBD owns the byte decoding.
COMMAND_ATTRS: dict[str, str] = {
    "rpm": "RPM",
    "speed": "SPEED",
    "coolant_temp": "COOLANT_TEMP",
    "throttle_pos": "THROTTLE_POS",
    "intake_air_temp": "INTAKE_TEMP",
    "timing_advance": "TIMING_ADVANCE",
    "o2_sensor_b1s1": "O2_B1S1",
    "engine_load": "ENGINE_LOAD",
    "maf": "MAF",
}

# PIDs with no python-OBD built-in; we define custom OBDCommands for these.
# (ELM_VOLTAGE exists but reads the *adapter's* voltage via AT RV, not the
# ECU's PID 0x42 -- hence the custom command.)
_CUSTOM_COMMANDS = ("battery_voltage", "dtc_count")

_stop = False


def _handle_signal(signum, frame):
    global _stop
    _stop = True


# --------------------------------------------------------------------------
# Profile loading
# --------------------------------------------------------------------------

def load_profile(path: str | Path = DEFAULT_PROFILE) -> tuple[list[dict], dict]:
    """Load the Aristo PID wishlist and poll plan from profile.yaml."""
    with open(path) as f:
        profile = yaml.safe_load(f)
    wishlist = profile["pid_wishlist"]
    poll_plan = profile.get("poll_plan", {})
    return wishlist, poll_plan


def pid_to_int(pid: str | None) -> int | None:
    """'0C' -> 12. Returns None for Toyota-extended PIDs ('extended')."""
    if pid is None or str(pid).lower() == "extended":
        return None
    return int(str(pid), 16)


def resolve_commands(wishlist: list[dict]) -> dict[str, dict]:
    """Map each wishlist entry to how it will be queried.

    Returns name -> {"pid": int|None, "unit": str, "status": str,
                     "kind": "builtin"|"custom"|"unmapped", "attr": str|None,
                     "note": str}.
    Does not touch the obd module, so it is safe to call without hardware.
    """
    resolved: dict[str, dict] = {}
    for entry in wishlist:
        name = entry["name"]
        pid = pid_to_int(entry.get("pid"))
        status = entry.get("status", "expected")
        if name in COMMAND_ATTRS:
            kind, attr, note = "builtin", COMMAND_ATTRS[name], ""
        elif name in _CUSTOM_COMMANDS:
            kind, attr, note = "custom", name, ""
        else:
            kind, attr = "unmapped", None
            note = ("no python-OBD mapping; Toyota-extended PID -- "
                    "identify via Techstream, then add a custom command")
        resolved[name] = {
            "pid": pid, "unit": entry.get("unit", ""),
            "status": status, "kind": kind, "attr": attr, "note": note,
            "mode": entry.get("mode", "01"),
        }
    return resolved


# --------------------------------------------------------------------------
# Custom OBDCommands (no python-OBD built-in exists for these)
# --------------------------------------------------------------------------

def _decode_module_voltage(messages) -> float:
    """PID 0x42: control-module voltage = (A*256 + B) / 1000, in volts."""
    d = messages[0].data[2:]
    return ((d[0] * 256) + d[1]) / 1000.0


def _decode_dtc_count(messages) -> int:
    """PID 0x01: byte A bit 7 = MIL on, bits 0-6 = stored DTC count."""
    d = messages[0].data[2:]
    return d[0] & 0x7F


def custom_command(name: str):
    """Build the custom OBDCommand for battery_voltage / dtc_count."""
    if obd is None:
        raise RuntimeError("python-OBD is not installed (pip install obd)")
    if name == "battery_voltage":
        return obd.OBDCommand(
            "Control module voltage",
            "ECU-reported system voltage, PID 0x42",
            b"0142", 2, _decode_module_voltage, obd.ECU.ENGINE, True)
    if name == "dtc_count":
        return obd.OBDCommand(
            "DTC count",
            "MIL + stored DTC count, PID 0x01 (see also Mode 03)",
            b"0101", 4, _decode_dtc_count, obd.ECU.ENGINE, True)
    raise ValueError(f"no custom command for {name!r}")


def get_command(name: str, entry: dict):
    """Return the live python-OBD command object for a resolved entry."""
    if obd is None:
        raise RuntimeError("python-OBD is not installed (pip install obd)")
    kind, attr = entry["kind"], entry["attr"]
    if kind == "builtin":
        return getattr(obd.commands, attr)
    if kind == "custom":
        return custom_command(name)
    raise ValueError(f"PID {name} has no command mapping")


# --------------------------------------------------------------------------
# Connection
# --------------------------------------------------------------------------

def _require_obd() -> None:
    if obd is None:
        raise SystemExit(
            "error: python-OBD is not installed.\n"
            "  pip install obd   (use the carlog venv: ~/.venvs/carlog)")


def connect(port: str, protocol: str = KLINE_PROTOCOL,
            baudrate: int = KLINE_BAUDRATE, timeout: float = 30.0):
    """Open the ELM327 and force ISO 9141-2.

    Tries 5-baud init first (old Toyota K-Lines usually prefer it), then
    one fast-init attempt. Raises ConnectionError with an actionable
    message if the ECU can't be reached.
    """
    _require_obd()
    last_err: Exception | None = None
    for attempt, fast in (("5-baud init", False), ("fast init", True)):
        try:
            conn = obd.OBD(portstr=port, protocol=protocol,
                            baudrate=baudrate, fast=fast, timeout=timeout)
        except Exception as exc:  # serial errors, bad port, etc.
            last_err = exc
            continue
        if conn.is_connected():
            print(f"ELM327 connected on {port} "
                  f"(protocol ISO 9141-2, {attempt})", flush=True)
            return conn
        try:
            conn.close()
        except Exception:
            pass
        last_err = ConnectionError(f"{attempt}: adapter opened but the ECU "
                                   f"did not answer")
    ports = []
    try:
        ports = obd.scan_serial()
    except Exception:
        pass
    raise ConnectionError(
        f"could not reach the ECU on {port} (ISO 9141-2).\n"
        f"  last error: {last_err}\n"
        f"  check: adapter plugged into the DLC3? key ON (engine off is fine)?\n"
        f"  check: '{port}' correct? visible ports: {ports or 'none found'}\n"
        f"  cross-check: phone app (Torque/OBD Fusion) forced to ISO 9141-2 --\n"
        f"  if the phone can't connect either, suspect the adapter or the\n"
        f"  port, not this software (profile.yaml verification step 4).")


# --------------------------------------------------------------------------
# Querying
# --------------------------------------------------------------------------

def query_pid(conn, name: str, pid: int | None, unit: str, cmd,
              ) -> tuple[float | None, str]:
    """Query one PID; returns (value, unit) or (None, unit) on NO DATA.

    Never raises for a failed read -- the poll loop must survive those.
    """
    try:
        resp = conn.query(cmd)
    except Exception as exc:
        print(f"  [{name}] query error: {exc}", flush=True)
        return None, unit
    if resp is None or resp.is_null():
        # ELM327 answered NO DATA / timeout: ECU doesn't serve this PID
        # (or not yet). Not fatal -- the loop continues.
        return None, unit
    value = resp.value
    if hasattr(value, "magnitude"):  # pint Quantity from built-in decoders
        value = value.magnitude
    try:
        return float(value), unit
    except (TypeError, ValueError):
        return None, unit


def probe_once(conn, resolved: dict[str, dict], dry_run: bool = False,
               ) -> dict[str, tuple[bool, str]]:
    """Try every unlikely/extended/verify PID exactly once.

    Returns name -> (answered, note). Never polled in the main loop.
    """
    results: dict[str, tuple[bool, str]] = {}
    for name, entry in resolved.items():
        if entry["status"] == "expected":
            continue
        if entry["kind"] == "unmapped":
            results[name] = (False, entry["note"])
            print(f"  [{name}] skipped ({entry['note']})", flush=True)
            continue
        cmd = name if dry_run else get_command(name, entry)
        value, unit = query_pid(conn, name, entry["pid"], entry["unit"], cmd)
        answered = value is not None
        note = f"answered: {value} {unit}" if answered else "no answer (NO DATA)"
        results[name] = (answered, note)
        print(f"  [{name}] one-shot probe: {note}", flush=True)
    return results


# --------------------------------------------------------------------------
# Poll loop
# --------------------------------------------------------------------------

def _build_jobs(resolved, poll_plan, fast: bool, dry_run: bool = False,
              ) -> list[dict]:
    """Jobs for the fast or slow loop: expected PIDs with a command mapping.

    dtc_count is expected but rides its own slow timer (poll plan's
    dtc_poll_interval_s), not the 1 Hz loop -- Mode 01 PID 01 is cheap but
    pointless at 1 Hz.

    In dry-run there is no obd module involved: each job's cmd is swapped
    for its PID name so _DryRunConnection.query() can answer it.
    """
    loop_names = set(poll_plan.get("fast_loop_pids" if fast
                                   else "slow_loop_pids", []))
    jobs = []
    for name, entry in resolved.items():
        if entry["status"] != "expected" or entry["kind"] == "unmapped":
            continue
        if name == "dtc_count":
            continue
        if loop_names and name not in loop_names:
            continue
        cmd = name if dry_run else get_command(name, entry)
        jobs.append({"name": name, "pid": entry["pid"],
                     "unit": entry["unit"], "cmd": cmd})
    return jobs


def poll_cycle(conn, store: Store, jobs: list[dict]) -> int:
    """Poll every job once; write samples to the obd2 table. Returns count."""
    ts = time.time()
    n = 0
    for job in jobs:
        value, unit = query_pid(conn, job["name"], job["pid"],
                                job["unit"], job["cmd"])
        store.log_obd2(ts, job["pid"], job["name"], value, unit)
        n += 1
    store.flush()
    return n


def run(port: str | None, db_path: str = DEFAULT_DB,
        interval: float | None = None, duration: float | None = None,
        dry_run: bool = False,
        profile_path: str | Path = DEFAULT_PROFILE,
        protocol: str = KLINE_PROTOCOL, baudrate: int = KLINE_BAUDRATE,
        max_reconnects: int = 10) -> Path:
    """Main K-Line polling loop. Returns the DB path on clean exit."""
    global _stop
    _stop = False  # a previous run (or test) may have set it via SIGINT
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    wishlist, poll_plan = load_profile(profile_path)
    resolved = resolve_commands(wishlist)

    if not dry_run and not port:
        raise SystemExit("error: --port is required (or use --dry-run)")

    store = Store(db_path, note="kline aristo-v300")

    fast_hz = float(poll_plan.get("fast_loop_hz", 5))
    slow_hz = float(poll_plan.get("slow_loop_hz", 1))
    slow_period = interval or (1.0 / slow_hz)
    fast_period = min(1.0 / fast_hz, slow_period)
    dtc_period = float(poll_plan.get("dtc_poll_interval_s", 300))

    if dry_run:
        conn = _DryRunConnection()
        print("dry-run: simulating ECU, no hardware touched", flush=True)
    else:
        conn = connect(port, protocol=protocol, baudrate=baudrate)

    try:
        # One-shot probes for unlikely/extended/verify PIDs (never looped).
        print("probing one-shot PIDs...", flush=True)
        probe_once(conn, resolved, dry_run=dry_run)

        fast_jobs = _build_jobs(resolved, poll_plan, fast=True,
                                dry_run=dry_run)
        slow_jobs = _build_jobs(resolved, poll_plan, fast=False,
                                dry_run=dry_run)
        dtc_entry = resolved.get("dtc_count")
        if dry_run:
            dtc_cmd = "dtc_count"
        else:
            dtc_cmd = (get_command("dtc_count", dtc_entry)
                       if dtc_entry and dtc_entry["kind"] != "unmapped"
                       else None)
        print(f"fast loop: {[j['name'] for j in fast_jobs]} "
              f"every {fast_period:.2f}s", flush=True)
        print(f"slow loop: {[j['name'] for j in slow_jobs]} "
              f"every {slow_period:.2f}s", flush=True)
        if dtc_cmd:
            print(f"DTC status every {dtc_period:.0f}s", flush=True)

        print(f"logging K-Line -> {store.path} "
              f"(session {store.session_id})", flush=True)
        t_end = time.time() + duration if duration else None
        next_fast = 0.0
        next_slow = 0.0
        next_dtc = 0.0
        samples = 0
        reconnects = 0
        while not _stop and (t_end is None or time.time() < t_end):
            now = time.time()
            try:
                if not dry_run and not conn.is_connected():
                    raise ConnectionError("ELM327 reports disconnected")
                if now >= next_fast:
                    next_fast = now + fast_period
                    samples += poll_cycle(conn, store, fast_jobs)
                if now >= next_slow:
                    next_slow = now + slow_period
                    samples += poll_cycle(conn, store, slow_jobs)
                if dtc_cmd and now >= next_dtc:
                    next_dtc = now + dtc_period
                    value, unit = query_pid(conn, "dtc_count",
                                            dtc_entry["pid"],
                                            dtc_entry["unit"], dtc_cmd)
                    store.log_obd2(now, dtc_entry["pid"], "dtc_count",
                                   value, unit)
                    samples += 1
                    if value:
                        print(f"  DTC count = {int(value)} "
                              f"(pull Mode 03 for codes)", flush=True)
            except (ConnectionError, OSError) as exc:
                # Mid-run disconnect: back off and reconnect, don't die.
                reconnects += 1
                if reconnects > max_reconnects:
                    raise SystemExit(f"error: lost the ECU {max_reconnects}x "
                                     f"in a row ({exc}); giving up") from exc
                wait = min(2 ** reconnects, 30)
                print(f"  link lost ({exc}); reconnect {reconnects}/"
                      f"{max_reconnects} in {wait}s", flush=True)
                try:
                    conn.close()
                except Exception:
                    pass
                time.sleep(wait)
                if not dry_run:
                    conn = connect(port, protocol=protocol, baudrate=baudrate)
                next_fast = next_slow = 0.0
            if duration is None:
                time.sleep(0.01)  # don't spin between polls
        print(f"done: {samples} K-Line samples", flush=True)
    finally:
        try:
            conn.close()
        except Exception:
            pass
        store.close()
    return store.path


# --------------------------------------------------------------------------
# Dry-run: simulated ECU for bench testing without hardware
# --------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, value):
        self.value = value

    def is_null(self):
        return self.value is None


def _dry_run_value(name: str, t: float):
    """Plausible parked-car values so the dash/DB path can be exercised."""
    table = {
        "rpm": 850 + 120 * math.sin(t * 0.7),
        "speed": 0.0,
        "coolant_temp": 88.0 + 2.0 * math.sin(t * 0.05),
        "throttle_pos": 0.0,
        "intake_air_temp": 32.0,
        "timing_advance": 12.0 + 3.0 * math.sin(t * 0.3),
        # narrowband O2 dithers rich/lean at idle -- looks alive on the dash
        "o2_sensor_b1s1": 0.45 + 0.40 * math.sin(t * 2.0),
        "engine_load": 18.0 + 4.0 * math.sin(t * 0.7),
        "battery_voltage": 13.8 + 0.2 * math.sin(t * 0.1),
        "dtc_count": 0,
        "maf": 3.5,
    }
    v = table.get(name)
    return round(v, 3) if v is not None else None


class _DryRunConnection:
    """Pretends to be an ELM327. query() takes the PID name."""

    def __init__(self):
        self._t0 = time.time()

    def is_connected(self):
        return True

    def close(self):
        pass

    def query(self, name):
        # query_pid() passes the resolved job's cmd; in dry-run the cmd
        # IS the PID name (jobs are built with cmd=name below).
        return _FakeResponse(_dry_run_value(name, time.time() - self._t0))


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="K-Line OBD-II poller for the Aristo V300 (JZS161). "
                    "Read-only: Mode 01/03 diagnostic requests only.")
    ap.add_argument("--port", default=None,
                    help="ELM327 serial port, e.g. /dev/cu.usbserial-XXXX "
                         "(macOS) or /dev/ttyUSB0 (Linux). Required unless "
                         "--dry-run.")
    ap.add_argument("--db", default=DEFAULT_DB,
                    help="SQLite DB path (default: %(default)s). Use the same "
                         "DB as the main logger so the dash reads one file.")
    ap.add_argument("--interval", type=float, default=None,
                    help="slow-loop poll interval in seconds "
                         "(default: from profile.yaml poll plan, ~1 Hz)")
    ap.add_argument("--duration", type=float, default=None,
                    help="stop after N seconds (default: run until signal)")
    ap.add_argument("--dry-run", action="store_true",
                    help="simulate the ECU; no hardware touched. Bench-test "
                         "the DB/dash path before going to the car.")
    ap.add_argument("--profile", default=str(DEFAULT_PROFILE),
                    help="path to the Aristo profile.yaml")
    ap.add_argument("--protocol", default=KLINE_PROTOCOL,
                    help="ELM327 protocol (default: 3 = ISO 9141-2)")
    ap.add_argument("--baudrate", type=int, default=KLINE_BAUDRATE,
                    help="ELM327 baudrate (default: 10400 for K-Line)")
    ap.add_argument("--list-pids", action="store_true",
                    help="print the PID wishlist, command mapping and poll "
                         "plan, then exit (no hardware needed)")
    args = ap.parse_args()

    if args.list_pids:
        wishlist, poll_plan = load_profile(args.profile)
        resolved = resolve_commands(wishlist)
        print(f"{'name':<18}{'pid':<8}{'status':<10}{'query-as'}")
        for entry in wishlist:
            r = resolved[entry["name"]]
            pid = f"0x{r['pid']:02X}" if r["pid"] is not None else "(ext)"
            how = {"builtin": f"obd.commands.{r['attr']}",
                   "custom": f"custom:{r['attr']}",
                   "unmapped": "NO MAPPING"}[r["kind"]]
            print(f"{entry['name']:<18}{pid:<8}{r['status']:<10}{how}")
        print(f"\npoll plan: fast {poll_plan.get('fast_loop_hz')} Hz "
              f"{poll_plan.get('fast_loop_pids')}; slow "
              f"{poll_plan.get('slow_loop_hz')} Hz "
              f"{poll_plan.get('slow_loop_pids')}")
        return

    try:
        run(args.port, db_path=args.db, interval=args.interval,
            duration=args.duration, dry_run=args.dry_run,
            profile_path=args.profile, protocol=args.protocol,
            baudrate=args.baudrate)
    except ConnectionError as exc:
        raise SystemExit(f"error: {exc}") from exc


if __name__ == "__main__":
    main()
