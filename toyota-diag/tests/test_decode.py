from toyotadiag import decode


def test_rpm_decode():
    assert decode.decode_mode01_pid(0x0C, bytes([0x1A, 0xF8])) == {"rpm": 1726.0}


def test_coolant_decode():
    assert decode.decode_mode01_pid(0x05, bytes([0x82])) == {"coolant_temp_c": 90}


def test_speed_decode():
    assert decode.decode_mode01_pid(0x0D, bytes([0x32])) == {"speed_kmh": 50}


def test_supported_pids_bitmap():
    out = decode.decode_mode01_pid(0x00, bytes([0xBE, 0x3E, 0xB8, 0x11]))
    assert out["supported_pids_01_20"][0] == "01"
    assert "0C" in out["supported_pids_01_20"]


def test_dtc_decode():
    assert decode.decode_dtcs(bytes([0x01, 0x33, 0x00, 0x00])) == ["P0133"]


def test_dtc_decode_all_zero():
    assert decode.decode_dtcs(bytes([0x00, 0x00])) == []


def test_summarize_mode01():
    res = decode.summarize_exchange("010C", "41 0C 1A F8")
    assert res["decoded"] == {"rpm": 1726.0}


def test_summarize_mode03():
    res = decode.summarize_exchange("03", "43 01 33 00 00")
    assert res["decoded"] == {"dtcs": ["P0133"]}


def test_summarize_toyota21_passthrough():
    res = decode.summarize_exchange("2101", "61 01 DE AD BE EF")
    assert res["decoded"] == {"toyota_ext21_raw": "DE AD BE EF"}
    assert "v0.1" in res["note"]


def test_summarize_no_data():
    res = decode.summarize_exchange("010C", "NO DATA")
    assert res["decoded"] is None
    assert res["note"]
