"""Tests for carlogger/kline.py (Aristo V300 K-Line poller).

The `obd` module is mocked: these tests must pass with no hardware and
whether or not python-OBD is installed. The fake is injected into
sys.modules BEFORE carlogger.kline is imported.

Run:  cd ~/workspace/car-logger && python3 -m pytest tests/test_kline.py -q
"""
import sqlite3
import sys
import types
from pathlib import Path

import pytest

# --------------------------------------------------------------------------
# Fake `obd` module (injected before kline is imported)
# --------------------------------------------------------------------------

PROFILE_NAMES = ["rpm", "speed", "coolant_temp", "throttle_pos",
                 "intake_air_temp", "timing_advance", "o2_sensor_b1s1",
                 "engine_load", "maf", "battery_voltage", "dtc_count"]


def _make_fake_obd():
    mod = types.ModuleType("obd")

    class _FakeCommand:
        def __init__(self, name):
            self.name = name  # profile name, so the fake conn can answer it

    commands = types.SimpleNamespace(
        **{attr: _FakeCommand(name)
           for name, attr in {
               "rpm": "RPM", "speed": "SPEED",
               "coolant_temp": "COOLANT_TEMP",
               "throttle_pos": "THROTTLE_POS",
               "intake_air_temp": "INTAKE_TEMP",
               "timing_advance": "TIMING_ADVANCE",
               "o2_sensor_b1s1": "O2_B1S1",
               "engine_load": "ENGINE_LOAD",
               "maf": "MAF"}.items()})
    mod.commands = commands

    class OBDCommand:
        def __init__(self, name, desc, command, nbytes, decoder, ecu,
                     fast=False):
            self.name = name
            self.desc = desc
            self.command = command
            self.decoder = decoder
            self.ecu = ecu

    mod.OBDCommand = OBDCommand
    mod.ECU = types.SimpleNamespace(ENGINE=2)
    mod.scan_serial = lambda: []
    return mod


sys.modules["obd"] = _make_fake_obd()

from carlogger import kline  # noqa: E402
from carlogger.db import Store  # noqa: E402

PROFILE = Path(kline.__file__).resolve().parent.parent / "vehicles" / \
    "aristo-v300" / "profile.yaml"


# --------------------------------------------------------------------------
# Fake connection / responses (stand-ins for ELM327 answers)
# --------------------------------------------------------------------------

class FakeQuantity:
    """Stands in for pint.Quantity: only .magnitude is read."""
    def __init__(self, magnitude):
        self.magnitude = magnitude


class FakeResponse:
    def __init__(self, value):
        self.value = value

    def is_null(self):
        return self.value is None


class FakeConnection:
    """answers: profile-name -> float value (None = NO DATA).
    fail_names: profile names whose query() raises (serial fault)."""

    def __init__(self, answers=None, fail_names=()):
        self.answers = answers or {}
        self.fail_names = set(fail_names)
        self.query_count: dict[str, int] = {}
        self._connected = True

    def is_connected(self):
        return self._connected

    def close(self):
        pass

    def query(self, cmd):
        name = cmd.name if hasattr(cmd, "name") else cmd
        self.query_count[name] = self.query_count.get(name, 0) + 1
        if name in self.fail_names:
            raise OSError("simulated serial fault")
        v = self.answers.get(name)
        if v is None:
            return FakeResponse(None)
        return FakeResponse(FakeQuantity(v))


@pytest.fixture()
def resolved():
    wishlist, _ = kline.load_profile(PROFILE)
    return kline.resolve_commands(wishlist)


@pytest.fixture()
def poll_plan():
    _, plan = kline.load_profile(PROFILE)
    return plan


# --------------------------------------------------------------------------
# Profile loading & PID -> command mapping
# --------------------------------------------------------------------------

def test_wishlist_loads_from_profile():
    wishlist, poll_plan = kline.load_profile(PROFILE)
    names = {e["name"] for e in wishlist}
    assert {"rpm", "speed", "coolant_temp", "throttle_pos",
            "engine_load"} <= names
    assert poll_plan["fast_loop_hz"] == 5
    assert "rpm" in poll_plan["fast_loop_pids"]


def test_pid_hex_mapping(resolved):
    assert resolved["rpm"]["pid"] == 0x0C
    assert resolved["speed"]["pid"] == 0x0D
    assert resolved["battery_voltage"]["pid"] == 0x42
    assert resolved["dtc_count"]["pid"] == 0x01
    # Toyota-extended PIDs have no hex code
    assert resolved["map_boost"]["pid"] is None
    assert resolved["trans_fluid_temp"]["pid"] is None


def test_builtin_command_mapping(resolved):
    assert resolved["rpm"]["kind"] == "builtin"
    assert resolved["rpm"]["attr"] == "RPM"
    assert resolved["o2_sensor_b1s1"]["attr"] == "O2_B1S1"
    cmd = kline.get_command("rpm", resolved["rpm"])
    assert cmd.name == "rpm"  # the fake command object


def test_custom_command_mapping(resolved):
    for name in ("battery_voltage", "dtc_count"):
        assert resolved[name]["kind"] == "custom"
    vcmd = kline.custom_command("battery_voltage")
    assert vcmd.command == b"0142"
    dcmd = kline.custom_command("dtc_count")
    assert dcmd.command == b"0101"
    with pytest.raises(ValueError):
        kline.custom_command("turbo_encabulator")


def test_extended_pids_unmapped_with_reason(resolved):
    for name in ("map_boost", "trans_fluid_temp"):
        assert resolved[name]["kind"] == "unmapped"
        assert "Techstream" in resolved[name]["note"]


# --------------------------------------------------------------------------
# Custom decoders (byte-level, as python-OBD would call them)
# --------------------------------------------------------------------------

class _Msg:
    def __init__(self, data):
        self.data = bytes(data)


def test_decode_module_voltage():
    # "41 42 2E 00" -> (0x2E*256 + 0x00)/1000 = 11.776 V
    v = kline._decode_module_voltage([_Msg([0x41, 0x42, 0x2E, 0x00])])
    assert v == pytest.approx(11.776)


def test_decode_dtc_count():
    # "41 01 83 ..." -> MIL on (bit 7), count = 0x83 & 0x7F = 3
    assert kline._decode_dtc_count([_Msg([0x41, 0x01, 0x83, 0, 0, 0])]) == 3
    # "41 01 00 ..." -> MIL off, no codes
    assert kline._decode_dtc_count([_Msg([0x41, 0x01, 0x00, 0, 0, 0])]) == 0


# --------------------------------------------------------------------------
# Query handling: values, NO DATA, exceptions
# --------------------------------------------------------------------------

def test_query_pid_value_and_unit(resolved):
    conn = FakeConnection(answers={"rpm": 812.5})
    cmd = kline.get_command("rpm", resolved["rpm"])
    value, unit = kline.query_pid(conn, "rpm", 0x0C, "rpm", cmd)
    assert value == pytest.approx(812.5)
    assert unit == "rpm"  # unit comes from the profile, not the decoder


def test_query_pid_no_data_returns_none(resolved):
    conn = FakeConnection(answers={})  # ECU answers nothing: NO DATA
    cmd = kline.get_command("speed", resolved["speed"])
    value, unit = kline.query_pid(conn, "speed", 0x0D, "km/h", cmd)
    assert value is None
    assert unit == "km/h"


def test_query_pid_plain_float_value():
    # custom decoders return plain floats, not pint Quantities
    conn = FakeConnection()
    conn.answers["battery_voltage"] = 13.8
    # bypass the fake-command name lookup: cmd double as the name here
    value, unit = kline.query_pid(conn, "battery_voltage", 0x42, "V",
                                  "battery_voltage")
    assert value == pytest.approx(13.8)


def test_query_pid_exception_does_not_raise(resolved):
    conn = FakeConnection(fail_names={"rpm"})
    cmd = kline.get_command("rpm", resolved["rpm"])
    value, _ = kline.query_pid(conn, "rpm", 0x0C, "rpm", cmd)
    assert value is None  # failed read -> None, loop survives


# --------------------------------------------------------------------------
# One-shot probes: unlikely/extended/verify tried once, never looped
# --------------------------------------------------------------------------

def test_probe_once_tries_unlikely_exactly_once(resolved):
    conn = FakeConnection(answers={"maf": 3.2})
    results = kline.probe_once(conn, resolved)
    assert results["maf"][0] is True
    assert "3.2" in results["maf"][1]
    assert conn.query_count.get("maf", 0) == 1
    # expected PIDs are not probed
    assert "rpm" not in results


def test_probe_once_skips_extended_with_reason(resolved):
    conn = FakeConnection(answers={})
    results = kline.probe_once(conn, resolved)
    for name in ("map_boost", "trans_fluid_temp"):
        answered, note = results[name]
        assert answered is False
        assert "Techstream" in note
    # extended PIDs were never even asked of the ECU...
    assert "map_boost" not in conn.query_count
    assert "trans_fluid_temp" not in conn.query_count
    assert "vin" not in conn.query_count
    # ...while the unlikely MAF probe did go out once
    assert conn.query_count.get("maf", 0) == 1


def test_probe_once_verify_status_treated_as_oneshot(resolved):
    # vin (status: verify, unmapped) -> skipped with a reason, not polled
    conn = FakeConnection(answers={})
    results = kline.probe_once(conn, resolved)
    assert "vin" in results
    assert results["vin"][0] is False


# --------------------------------------------------------------------------
# Poll loop: job split, resilience, DB writes
# --------------------------------------------------------------------------

def test_fast_slow_job_split(resolved, poll_plan):
    fast = kline._build_jobs(resolved, poll_plan, fast=True)
    slow = kline._build_jobs(resolved, poll_plan, fast=False)
    fast_names = {j["name"] for j in fast}
    slow_names = {j["name"] for j in slow}
    assert fast_names == {"rpm", "speed", "throttle_pos", "engine_load"}
    # extended PIDs have no mapping and must not appear in any loop
    assert "map_boost" not in slow_names
    assert "trans_fluid_temp" not in slow_names
    # dtc_count rides its own timer, not the fast/slow loops
    assert "dtc_count" not in fast_names | slow_names
    assert slow_names >= {"coolant_temp", "battery_voltage"}


def test_failed_read_does_not_kill_cycle(resolved, poll_plan, tmp_path):
    store = Store(tmp_path / "t.db")
    conn = FakeConnection(answers={"rpm": 900.0, "speed": 50.0},
                          fail_names={"throttle_pos"})
    jobs = kline._build_jobs(resolved, poll_plan, fast=True)
    n = kline.poll_cycle(conn, store, jobs)
    store.close()
    assert n == len(jobs)
    rows = sqlite3.connect(tmp_path / "t.db").execute(
        "SELECT name, value FROM obd2").fetchall()
    by_name = dict(rows)
    assert by_name["rpm"] == pytest.approx(900.0)
    assert by_name["throttle_pos"] is None  # failed read logged as NULL
    assert len(rows) == len(jobs)  # every job wrote a row


def test_db_write_path_columns(resolved, poll_plan, tmp_path):
    dbp = tmp_path / "drive.db"
    store = Store(dbp, note="kline test")
    conn = FakeConnection(answers={"coolant_temp": 91.0})
    jobs = [j for j in kline._build_jobs(resolved, poll_plan, fast=False)
            if j["name"] == "coolant_temp"]
    kline.poll_cycle(conn, store, jobs)
    store.close()
    row = sqlite3.connect(dbp).execute(
        "SELECT session_id, ts, pid, name, value, unit FROM obd2").fetchone()
    assert row is not None
    sid, ts, pid, name, value, unit = row
    assert pid == 0x05 and isinstance(pid, int)
    assert name == "coolant_temp"
    assert value == pytest.approx(91.0)
    assert unit == "degC"
    assert ts > 0
    # session row exists and matches
    sess = sqlite3.connect(dbp).execute(
        "SELECT id FROM sessions").fetchone()
    assert sess[0] == sid


# --------------------------------------------------------------------------
# End to end: dry-run needs no hardware and no obd module
# --------------------------------------------------------------------------

def test_dry_run_writes_samples(tmp_path):
    dbp = tmp_path / "dry.db"
    out = kline.run(None, db_path=str(dbp), interval=0.2, duration=0.7,
                    dry_run=True, profile_path=PROFILE)
    assert Path(out) == dbp
    names = {r[0] for r in sqlite3.connect(dbp).execute(
        "SELECT DISTINCT name FROM obd2").fetchall()}
    assert {"rpm", "speed", "coolant_temp", "battery_voltage",
            "dtc_count"} <= names
    n = sqlite3.connect(dbp).execute("SELECT COUNT(*) FROM obd2").fetchone()[0]
    assert n > 10  # fast loop actually ran more than once


def test_list_pids_does_not_need_hardware(capsys):
    import sys as _sys
    old = _sys.argv
    _sys.argv = ["kline", "--list-pids", "--profile", str(PROFILE)]
    try:
        kline.main()
    finally:
        _sys.argv = old
    out = capsys.readouterr().out
    assert "rpm" in out and "0x0C" in out
    assert "NO MAPPING" in out  # extended PIDs flagged
