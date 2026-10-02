"""Validate vehicles/aristo-v300/profile.yaml.

These tests guard the profile against the two failure modes that matter:
1. Structural rot — a key gets renamed/deleted and the tooling breaks.
2. Dishonest certainty — a protocol claim without a confidence level, or a
   pinout that contradicts the no-CAN finding, slipping in unnoticed.

Run:  python3 -m pytest vehicles/aristo-v300/test_profile.py -v
"""

from pathlib import Path

import pytest
import yaml

PROFILE = Path(__file__).with_name("profile.yaml")

ALLOWED_PID_STATUS = {"expected", "unlikely", "extended", "verify"}
ALLOWED_CONFIDENCE = {"high", "medium", "verify"}
CORE_PIDS = {"rpm", "speed", "throttle_pos"}  # need 5 Hz; coolant is fine at 1 Hz


@pytest.fixture(scope="module")
def profile():
    assert PROFILE.exists(), f"profile.yaml missing at {PROFILE}"
    with open(PROFILE) as f:
        data = yaml.safe_load(f)
    assert isinstance(data, dict), "profile.yaml must load to a mapping"
    return data


@pytest.fixture(scope="module")
def pid_names(profile):
    return {p["name"] for p in profile["pid_wishlist"]}


# --- structure ---------------------------------------------------------------

def test_top_level_sections(profile):
    for key in ("vehicle", "dlc3", "diagnostics", "pid_wishlist",
                "poll_plan", "notes"):
        assert key in profile, f"missing top-level section: {key}"


def test_vehicle_identity(profile):
    v = profile["vehicle"]
    for key in ("make", "model", "chassis", "engine", "transmission",
                "drivetrain", "market"):
        assert v.get(key), f"vehicle.{key} must be non-empty"
    assert v["chassis"] == "JZS161"
    assert v["market"] == "JDM"


def test_dlc3_pinout(profile):
    dlc = profile["dlc3"]
    assert dlc.get("location"), "dlc3.location must be non-empty"
    pins = dlc.get("populated_pins")
    assert isinstance(pins, list) and all(isinstance(p, int) for p in pins), \
        "populated_pins must be a list of ints"
    assert pins == [4, 7, 13, 16], \
        "populated_pins changed — if the car really differs, update the " \
        "ClubLexus source note and can_pins_present together"
    for entry in dlc["pinout"]:
        for key in ("pin", "function", "confidence"):
            assert key in entry, f"pinout entry missing {key}: {entry}"
        assert entry["confidence"] in ALLOWED_CONFIDENCE, \
            f"pin {entry['pin']}: confidence must be one of {ALLOWED_CONFIDENCE}"


def test_no_can_pins_without_flag(profile):
    """The profile's headline finding is 'no CAN on this chassis'.
    If someone ever adds pins 6/14 to populated_pins, can_pins_present must
    flip to true in the same edit — otherwise the profile contradicts itself."""
    dlc = profile["dlc3"]
    can_pins = {6, 14} & set(dlc["populated_pins"])
    if can_pins:
        assert dlc.get("can_pins_present") is True, \
            f"CAN pins {sorted(can_pins)} listed but can_pins_present is not true"
    else:
        assert dlc.get("can_pins_present") is False


def test_verification_procedure(profile):
    proc = profile["diagnostics"]["verification_procedure"]
    assert isinstance(proc, list) and len(proc) >= 5, \
        "verification procedure must have at least 5 steps"
    steps = [s["step"] for s in proc]
    assert steps == sorted(steps) and len(set(steps)) == len(steps), \
        "verification steps must be uniquely and increasingly numbered"
    for s in proc:
        for key in ("step", "title", "action", "pass"):
            assert s.get(key), f"verification step {s.get('step')} missing {key!r}"
    titles = " ".join(s["title"].lower() for s in proc)
    assert "dlc3" in titles or "find" in titles
    assert "k-line" in titles or "kline" in titles or "k-line" in " ".join(
        s["action"].lower() for s in proc)


def test_protocol_has_confidence(profile):
    d = profile["diagnostics"]
    assert d.get("protocol"), "diagnostics.protocol must be non-empty"
    assert d.get("protocol_confidence") in ALLOWED_CONFIDENCE
    assert "K-Line" in d["protocol"] or "9141" in d["protocol"], \
        "protocol changed away from ISO 9141-2 K-Line — deliberate?"


# --- PID wishlist ------------------------------------------------------------

def test_pid_wishlist_schema(profile):
    assert isinstance(profile["pid_wishlist"], list)
    assert len(profile["pid_wishlist"]) >= 10
    for p in profile["pid_wishlist"]:
        for key in ("name", "mode", "pid", "unit", "status", "why"):
            assert key in p, f"PID entry missing {key!r}: {p}"
        assert p["status"] in ALLOWED_PID_STATUS, \
            f"PID {p['name']}: bad status {p['status']!r}"


def test_pid_names_unique(profile):
    names = [p["name"] for p in profile["pid_wishlist"]]
    assert len(names) == len(set(names)), "duplicate PID names in wishlist"


def test_core_pids_present(pid_names):
    missing = CORE_PIDS - pid_names
    assert not missing, f"core PIDs missing from wishlist: {missing}"


def test_boost_and_trans_temp_are_extended(pid_names, profile):
    """MAP/boost and trans temp are the two signals that NEED Toyota extended
    PIDs — they must be flagged as such, never silently 'expected'."""
    by_name = {p["name"]: p for p in profile["pid_wishlist"]}
    for name in ("map_boost", "trans_fluid_temp"):
        assert name in by_name, f"{name} missing from wishlist"
        assert by_name[name]["status"] == "extended", \
            f"{name} must be status 'extended' (Toyota-specific PID, unverified)"


def test_poll_plan_references_real_pids(profile, pid_names):
    plan = profile["poll_plan"]
    for loop in ("fast_loop_pids", "slow_loop_pids"):
        for name in plan[loop]:
            assert name in pid_names, \
                f"poll_plan.{loop} references unknown PID {name!r}"
    fast = set(plan["fast_loop_pids"])
    assert CORE_PIDS <= fast, \
        f"fast loop must include core PIDs; missing {CORE_PIDS - fast}"
    assert len(plan["fast_loop_pids"]) <= 6, \
        "fast loop too wide for K-Line bandwidth (~5-10 reads/sec)"


# --- honesty -----------------------------------------------------------------

def test_no_unfinished_placeholders():
    text = PROFILE.read_text()
    for marker in ("TODO", "FIXME", "XXX", "TBD", "???"):
        assert marker not in text, f"unfinished placeholder {marker!r} in profile.yaml"


def test_confidence_levels_everywhere(profile):
    """Every load-bearing claim carries a confidence level."""
    assert profile["dlc3"].get("location_confidence") in ALLOWED_CONFIDENCE
    assert profile["diagnostics"].get("protocol_confidence") in ALLOWED_CONFIDENCE
