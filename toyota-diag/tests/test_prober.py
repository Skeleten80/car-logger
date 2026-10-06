from toyotadiag import prober, protocols

from fake_serial import FakeSerial


def _session_replies():
    return [
        "ELM327 v1.5\r\r",  # ATZ
        "OK\r\r",  # ATE0
        "OK\r\r",  # ATL0
        "OK\r\r",  # ATH1
        "12.4V\r\r",  # ATRV
    ]


def test_run_probe_logs_everything(tmp_path):
    fake = FakeSerial("COM1", timeout=0.5)
    fake.queue(
        *_session_replies(),
        "OK\r\r",  # ATSP3
        *["NO DATA\r\r"] * 8,
        "41 0C 1A F8\r\r",  # 010C answers
    )
    out = tmp_path / "probe.jsonl"
    records = prober.run_probe(
        "COM1",
        attempt_names=["iso9141_5baud"],
        out_path=str(out),
        serial_factory=lambda *a, **k: fake,
    )
    # 5 session + 1 init + 9 payloads
    assert len(records) == 15
    assert records[0].tx == "ATZ"
    assert records[5].attempt == "iso9141_5baud" and records[5].phase == "init"
    assert records[-1].tx == "0902"

    lines = out.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 15

    summary = prober.summarize(records)
    assert summary["iso9141_5baud"] == {"sent": 9, "answered": 1}


def test_adapter_error_is_logged_not_raised(tmp_path):
    fake = FakeSerial("COM1", timeout=0.05)  # nothing queued -> ELM327Error
    out = tmp_path / "probe.jsonl"
    records = prober.run_probe(
        "COM1", attempt_names=[], out_path=str(out), serial_factory=lambda *a, **k: fake
    )
    assert all(r.rx.startswith("<adapter-error") for r in records)
    assert out.exists()


def test_monitor_attempt_uses_long_timeout():
    fake = FakeSerial("COM1", timeout=0.5)
    fake.queue(*_session_replies(), "OK\r\r", "\r\r")  # ATMA: silence
    records = prober.run_probe(
        "COM1",
        attempt_names=["bus_monitor"],
        out_path=None,
        atma_seconds=0.05,
        serial_factory=lambda *a, **k: fake,
    )
    mon = [r for r in records if r.phase == "monitor"]
    assert len(mon) == 1 and mon[0].tx == "ATMA"


def test_all_attempts_enumerated():
    names = [a.name for a in protocols.PROBE_ATTEMPTS]
    assert "iso9141_5baud" in names and "toyota_mode21" in names
