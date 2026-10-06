import pytest

from toyotadiag.elm327 import ELM327, ELM327Error

from fake_serial import FakeSerial


def make_elm(*replies, timeout=0.5):
    fake = FakeSerial("COM1", timeout=timeout)
    fake.queue(*replies)
    elm = ELM327("COM1", timeout=timeout, serial_factory=lambda *a, **k: fake)
    return elm, fake


def test_command_strips_echo_and_prompt():
    elm, fake = make_elm("010C\r41 0C 1A F8\r\r")
    assert elm.command("010C") == "41 0C 1A F8"
    assert fake.written == [b"010C\r"]


def test_command_without_echo():
    elm, fake = make_elm("41 0C 1A F8\r\r")
    assert elm.command("010C") == "41 0C 1A F8"


def test_command_collapses_whitespace():
    elm, fake = make_elm("41  0C\r\n1A   F8\r\r")
    assert elm.command("010C") == "41 0C 1A F8"


def test_no_response_raises():
    elm, _ = make_elm(timeout=0.05)  # nothing queued
    with pytest.raises(ELM327Error):
        elm.command("010C")


def test_reset_sends_atz():
    elm, fake = make_elm("ELM327 v1.5\r\r")
    assert elm.reset() == "ELM327 v1.5"
    assert fake.written == [b"ATZ\r"]


def test_context_manager_closes():
    elm, fake = make_elm("OK\r\r")
    with elm:
        elm.command("ATE0")
    assert fake.closed
