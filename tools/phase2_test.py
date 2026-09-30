"""Phase-2 end-to-end test: DBC decode + live dash API, no hardware.

Spins up a virtual CAN bus with:
  - a fake OBD-II ECU (reused from the phase-1 smoke test),
  - background chatter,
  - a raw-frame sender emitting ENGINE_DATA frames encoded with cantools
    from a minimal test DBC.

Runs the logger in 'both' mode with DBC decoding on, serves the dash
API on an ephemeral port, then asserts:
  - the signals table holds decoded EngineRPM ~= 800,
  - GET /api/latest exposes them,
  - GET /api/info lists the DBC,
  - GET /api/history returns samples,
  - the /api/live SSE stream pushes a first event with the signals.
"""
import http.client
import json
import sqlite3
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import can

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import smoke_test  # noqa: E402  (fake_ecu + chatter, guarded by __main__)
from carlogger import dash, logger  # noqa: E402

CHANNEL = "phase2-test-bus"
TEST_DBC = """VERSION ""

NS_ :
\tNS_DESC_
\tCM_
\tBA_DEF_
\tBA_
\tVAL_
\tCAT_DEF_
\tCAT_
\tFILTER
\tBA_DEF_DEF_
\tEV_DATA_
\tENVVAR_DATA_
\tSGTYPE_
\tSGTYPE_VAL_
\tBA_DEF_SGTYPE_
\tBA_SGTYPE_
\tSIG_TYPE_REF_
\tVAL_TABLE_
\tSIG_GROUP_
\tSIG_VALTYPE_
\tSIGTYPE_VALTYPE_
\tBO_TX_BU_
\tBA_DEF_REL_
\tBA_REL_
\tBA_DEF_DEF_REL_
\tBU_SG_REL_
\tBU_EV_REL_
\tBU_BO_REL_
\tSG_MUL_VAL_

BS_:

BU_: TESTECU

BO_ 291 ENGINE_DATA: 8 TESTECU
 SG_ EngineRPM : 0|16@1+ (0.25,0) [0|16383.75] "rpm" TESTECU
 SG_ ThrottlePos : 16|8@1+ (0.392157,0) [0|100] "%" TESTECU
"""


def raw_sender(stop: threading.Event, dbc_path: str):
    """Emit ENGINE_DATA frames like a real ECU would."""
    import cantools
    bus = can.interface.Bus(interface="virtual", channel=CHANNEL)
    db = cantools.database.load_file(dbc_path)
    msg = db.get_message_by_name("ENGINE_DATA")
    while not stop.is_set():
        data = msg.encode({"EngineRPM": 800.0, "ThrottlePos": 39.2})
        bus.send(can.Message(arbitration_id=0x123, data=data,
                             is_extended_id=False))
        time.sleep(0.05)
    bus.shutdown()


def get_json(port: int, path: str) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}",
                                timeout=5) as r:
        return json.loads(r.read())


def first_sse_event(port: int) -> dict:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", "/api/live", headers={"Accept": "text/event-stream"})
    resp = conn.getresponse()
    assert resp.status == 200, f"SSE status {resp.status}"
    assert "text/event-stream" in resp.getheader("Content-Type"), \
        "expected SSE content type"
    deadline = time.time() + 10
    while time.time() < deadline:
        line = resp.readline().decode()
        if line.startswith("data:"):
            conn.close()
            return json.loads(line[5:])
    conn.close()
    raise AssertionError("no SSE data event within 10 s")


def main():
    tmp = Path(tempfile.mkdtemp(prefix="carlogger-phase2-"))
    dbc_path = tmp / "test.dbc"
    dbc_path.write_text(TEST_DBC)

    cfg = {
        "bus": {"interface": "virtual", "channel": CHANNEL},
        "mode": {"mode": "both"},
        "obd2": {"pids": [12, 13], "poll_interval": 0.2,
                 "response_timeout": 0.5},
        "storage": {"path": str(tmp / "drive.db")},
        "decode": {"dbc_path": str(dbc_path), "vehicle": "Test Rig"},
        "dash": {"host": "127.0.0.1", "port": 0},
    }

    smoke_test.CHANNEL = CHANNEL
    server = dash.create_server(cfg)
    port = server.server_address[1]
    srv_thread = threading.Thread(target=server.serve_forever, daemon=True)
    srv_thread.start()

    stop = threading.Event()
    threads = [threading.Thread(target=smoke_test.fake_ecu, args=(stop,)),
               threading.Thread(target=smoke_test.chatter, args=(stop,)),
               threading.Thread(target=raw_sender, args=(stop, str(dbc_path)))]
    for t in threads:
        t.start()
    try:
        db_path = logger.run(cfg, duration=3.0)
    finally:
        stop.set()
        for t in threads:
            t.join()

    # 1. signals table holds decoded values
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT signal, value, unit, message FROM signals").fetchall()
    conn.close()
    rpm_vals = [r[1] for r in rows if r[0] == "EngineRPM"]
    tps_vals = [r[1] for r in rows if r[0] == "ThrottlePos"]
    print(f"decoded signals: {len(rows)} rows, "
          f"EngineRPM x{len(rpm_vals)}, ThrottlePos x{len(tps_vals)}")
    assert rpm_vals, "no EngineRPM rows decoded"
    assert all(abs(v - 800.0) < 1.0 for v in rpm_vals), \
        f"EngineRPM decode wrong: {rpm_vals[:3]}"
    assert tps_vals and all(abs(v - 39.2) < 0.5 for v in tps_vals), \
        f"ThrottlePos decode wrong: {tps_vals[:3]}"

    # 2. /api/latest exposes OBD-II + decoded signals
    latest = get_json(port, "/api/latest")
    assert abs(latest["signals"]["EngineRPM"]["value"] - 800.0) < 1.0, latest
    assert latest["signals"]["EngineRPM"]["unit"] == "rpm"
    assert latest["signals"]["EngineRPM"]["message"] == "ENGINE_DATA"
    assert "rpm" in latest["obd2"], "OBD-II rpm missing from /api/latest"
    print(f"/api/latest ok: obd2 keys={sorted(latest['obd2'])}, "
          f"signals={sorted(latest['signals'])}")

    # 3. /api/info lists the DBC + vehicle label
    info = get_json(port, "/api/info")
    assert info["dbc_files"] == ["test.dbc"], info
    assert info["vehicle"] == "Test Rig"
    print(f"/api/info ok: {info}")

    # 4. /api/history returns a time series
    hist = get_json(port, "/api/history?signal=EngineRPM&limit=50")
    assert len(hist["samples"]) > 5, hist
    assert all(abs(v - 800.0) < 1.0 for _, v in hist["samples"])
    print(f"/api/history ok: {len(hist['samples'])} samples")

    # 5. SSE stream pushes live events
    event = first_sse_event(port)
    assert abs(event["signals"]["EngineRPM"]["value"] - 800.0) < 1.0, event
    print("SSE /api/live ok: first event carries decoded signals")

    server.shutdown()
    server.server_close()
    print("PHASE-2 TEST PASSED")


if __name__ == "__main__":
    main()
