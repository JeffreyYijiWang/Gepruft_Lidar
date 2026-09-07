import pytest

from lms200.protocol.commands import (
    Mode,
    baud_rate,
    configuration_request,
    operating_mode,
    status_request,
    type_request,
    variant,
)
from lms200.protocol.framing import Framer
from lms200.protocol.responses import DeviceError, ProtocolError, StatusByte, confirm, response


def test_commands_match_official_vectors(golden):
    commands = {
        "status": status_request(),
        "type": type_request(),
        "read_config": configuration_request(),
        "installation": operating_mode(Mode.INSTALLATION),
        "start": operating_mode(Mode.CONTINUOUS),
        "stop": operating_mode(Mode.ON_REQUEST),
        "variant180_1": variant(180, 1),
        "variant180_half": variant(180, 0.5),
        "variant100_quarter": variant(100, 0.25),
    }
    commands.update({f"baud{b}": baud_rate(b) for b in (9600, 19200, 38400, 500000)})
    for name, cmd in commands.items():
        assert cmd.telegram() == golden[name]


def test_reject_unsupported_geometry():
    with pytest.raises(ValueError):
        variant(180, 0.25)


def test_address_validation(golden):
    frame = Framer().feed(golden["mode_response_81"])[0]
    confirm(response(frame), b"\x20\x24")
    with pytest.raises(ProtocolError):
        response(frame, address=2)


def test_status_bits():
    result = StatusByte.decode(0xD2)
    assert result.severity == "warning" and result.pollution and result.implausible
    with pytest.raises(ProtocolError):
        StatusByte.decode(0x17)


def test_rejected_mode(golden):
    from lms200.protocol.framing import encode

    frame = Framer().feed(encode(b"\xa0\x01\x10", 0x80))[0]
    with pytest.raises(DeviceError):
        confirm(response(frame), b"\x20\x00")
