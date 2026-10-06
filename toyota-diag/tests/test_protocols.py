import pytest

from toyotadiag import protocols


def test_attempt_names_unique():
    names = [a.name for a in protocols.PROBE_ATTEMPTS]
    assert len(names) == len(set(names))


def test_payloads_are_even_length_hex():
    for attempt in protocols.PROBE_ATTEMPTS:
        for payload in attempt.payloads:
            if payload == "ATMA":
                continue
            assert len(payload) % 2 == 0, f"{attempt.name}: {payload}"
            int(payload, 16)  # raises if not hex


def test_get_attempt_roundtrip():
    for attempt in protocols.PROBE_ATTEMPTS:
        assert protocols.get_attempt(attempt.name) is attempt


def test_get_attempt_unknown_raises():
    with pytest.raises(KeyError):
        protocols.get_attempt("nope")


def test_generic_payloads_include_essentials():
    assert "010C" in protocols.GENERIC_PAYLOADS  # RPM
    assert "03" in protocols.GENERIC_PAYLOADS  # DTCs
