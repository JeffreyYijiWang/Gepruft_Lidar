from struct import pack

import pytest

from lms200.protocol.framing import Framer, encode
from lms200.protocol.measurements import OVERFLOW, decode_scan
from lms200.protocol.responses import Configuration, ProtocolError, decode_status, response
from lms200.transports.simulator import SimulatorTransport, default_configuration


def scan_reply(values, unit=1, extra=b"", header_flags=0):
    # Synthetic fixture derived from Listing Table 7-25; not an official complete example.
    data = b"\xb0" + pack("<H", len(values) | (unit << 14) | header_flags)
    data += b"".join(pack("<H", v) for v in values) + extra + b"\x10"
    return response(Framer().feed(encode(data, 0x81))[0])


def test_coordinates_and_100_degree_origin():
    config = default_configuration()
    scan = decode_scan(scan_reply([1000] * 101), 100, 1, config, 3)
    assert scan.starting_angle == 40
    assert scan.points[0].angle_deg == 40 and scan.points[-1].angle_deg == 140
    assert scan.points[50].x == pytest.approx(0, abs=1e-12)
    assert scan.points[50].y == 1
    assert scan.points[0].x > 0 and scan.points[-1].x < 0


def test_centimeters_flags_and_overflow():
    config = default_configuration().updated("cm", indices=False)
    values = [100 | 0xE000] + list(OVERFLOW) + [100] * 94
    scan = decode_scan(scan_reply(values, unit=0), 100, 1, config, 1)
    assert scan.points[0].distance_m == 1
    assert scan.points[0].flags == ("field_a", "field_b", "field_c")
    for point, flag in zip(scan.points[1:7], OVERFLOW.values(), strict=True):
        assert point.distance_m is None and flag in point.flags


def test_indices():
    config = default_configuration().updated("mm", indices=True)
    scan = decode_scan(scan_reply([1000] * 181, extra=b"\xf1\xff"), 180, 1, config, 9)
    assert (scan.scan_index, scan.telegram_index) == (241, 255)


@pytest.mark.parametrize("mutation", ["unit", "count", "partial", "length", "mode"])
def test_invalid_measurements(mutation):
    config = default_configuration()
    reply = scan_reply(
        [1000] * (100 if mutation == "count" else 101),
        unit=0 if mutation == "unit" else 1,
        extra=b"\x00" if mutation == "length" else b"",
        header_flags=0x2000 if mutation == "partial" else 0,
    )
    if mutation == "mode":
        raw = bytearray(config.raw)
        raw[5] = 0x0D
        config = Configuration(bytes(raw))
    with pytest.raises(ProtocolError):
        decode_scan(reply, 100, 1, config, 1)


def test_status_layouts_and_reserved_block_correction():
    sim = SimulatorTransport()
    raw = sim.status_data()
    for data in (raw, raw[:11] + raw[17:]):
        reply = response(Framer().feed(encode(b"\xb1" + data + b"\x10", 0x80))[0])
        status = decode_status(reply)
        assert status.firmware == "V02.10" and status.angle == 180
        assert status.resolution == 0.5 and status.baud == 9600 and status.unit == "mm"


def test_config_preserves_unrelated_bytes():
    data = bytearray(default_configuration().raw)
    data[0], data[4], data[-1] = 19, 0x05, 73
    changed = Configuration(bytes(data)).updated("cm")
    assert changed.raw[:4] == data[:4] and changed.raw[7:] == data[7:]
    assert changed.raw[4] == 7 and changed.raw[6] == 0
