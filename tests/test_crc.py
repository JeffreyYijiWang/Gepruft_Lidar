from lms200.protocol.crc import crc16


def test_official_golden_values(golden):
    for name, raw in golden.items():
        assert crc16(raw[:-2]) == int.from_bytes(raw[-2:], "little"), name


def test_empty():
    assert crc16(b"") == 0
