"""Strict response decoding using named blocks from the Telegram Listing."""

from dataclasses import dataclass
from struct import unpack_from

from .commands import STATUS_BAUD_CODES, validate_geometry
from .framing import Frame


class ProtocolError(Exception):
    pass


class DeviceError(ProtocolError):
    pass


@dataclass(frozen=True)
class StatusByte:
    raw: int
    severity: str
    source: str
    restart_high: bool
    implausible: bool
    pollution: bool

    @classmethod
    def decode(cls, raw: int) -> "StatusByte":
        # Listing §8 p106. Unassigned severity codes are not silently treated as OK.
        severity = {0: "ok", 1: "info", 2: "warning", 3: "error", 4: "fatal"}.get(raw & 7)
        if severity is None:
            raise ProtocolError("Reserved scanner status severity")
        source = {2: "LMS type 6", 3: "special device"}.get((raw >> 3) & 3, "reserved")
        return cls(raw, severity, source, bool(raw & 0x20), bool(raw & 0x40), bool(raw & 0x80))


@dataclass(frozen=True)
class Response:
    command: int
    data: bytes
    status: StatusByte
    frame: Frame


def response(frame: Frame, address: int = 0) -> Response:
    # Broadcast replies differ across manuals: 80 (listing) and 81 (setup).
    # Accept only these for broadcast; individual addressing must match exactly.
    expected = {0x80, 0x81} if address == 0 else {address | 0x80}
    if frame.address not in expected:
        raise ProtocolError("Unexpected response address")
    if len(frame.payload) < 2 or frame.command < 0x80:
        raise ProtocolError("Invalid response payload")
    result = Response(
        frame.command, frame.payload[1:-1], StatusByte.decode(frame.payload[-1]), frame
    )
    if result.command == 0x92:
        raise DeviceError("Scanner rejected the command or its operating-state sequence (92h)")
    return result


def require_healthy(reply: Response) -> None:
    if reply.status.severity in ("error", "fatal"):
        raise DeviceError(f"Scanner reports {reply.status.severity}")


def confirm(reply: Response, request_payload: bytes) -> None:
    if reply.command in (0xA0, 0xBB, 0xF7):
        require_healthy(reply)
    if reply.command == 0xA0:
        if reply.data != b"\x00":
            # Listing p45 repeats 01 for password/fault; do not invent a distinction.
            raise DeviceError("Operating mode/baud change rejected (password or device fault)")
    elif reply.command == 0xBB:
        if len(reply.data) != 5 or reply.data[0] != 1 or reply.data[1:] != request_payload[1:]:
            raise DeviceError("Variant change failed or readback differs")
    elif reply.command == 0xF7:
        if len(reply.data) != len(request_payload) or reply.data[0] != 1:
            raise DeviceError("Configuration was not accepted")
        if reply.data[1:] != request_payload[1:]:
            raise DeviceError("Configuration confirmation differs from requested data")


@dataclass(frozen=True)
class Configuration:
    raw: bytes

    def __post_init__(self) -> None:
        if len(self.raw) not in (32, 34):
            raise ProtocolError(f"Unsupported configuration length {len(self.raw)}")

    @property
    def mode(self) -> int:
        return self.raw[5]  # §7.46 Table 7-122 block D

    @property
    def unit(self) -> str:
        if self.raw[6] not in (0, 1):
            raise ProtocolError("Reserved measurement unit")
        return "mm" if self.raw[6] else "cm"

    @property
    def indices(self) -> bool:
        return bool(self.raw[4] & 2)  # p97 block C bit1

    def updated(self, unit: str, indices: bool = True) -> "Configuration":
        if unit not in ("mm", "cm"):
            raise ValueError("Expected mm or cm")
        data = bytearray(self.raw)
        data[4] = (data[4] | 2) if indices else (data[4] & ~2)
        data[5] = 2  # p98: 13-bit distance, field A/B/C flags; not reserved legacy 0D.
        data[6] = int(unit == "mm")
        return Configuration(bytes(data))


@dataclass(frozen=True)
class DeviceStatus:
    firmware: str
    operating_mode: int
    device_error: int
    angle: int
    resolution: float
    baud: int
    unit: str
    measuring_mode: int
    permanent_baud: bool
    address: int
    raw_hex: str


def decode_status(reply: Response) -> DeviceStatus:
    if reply.command != 0xB1:
        raise ProtocolError("Expected B1 status")
    data = reply.data
    # Table 7-33 sums to 146 bytes, but Table 7-34 specifies 152. SICK Toolbox
    # _getSickStatus corroborates six additional reserved bytes before block E.
    # Support those two explicit layouts only; never search for plausible fields.
    if len(data) not in (146, 152):
        raise ProtocolError("Unsupported status length; expected 146 or 152 data bytes")
    shift = 6 if len(data) == 152 else 0
    angle, resolution = unpack_from("<HH", data, 100 + shift)
    try:
        validate_geometry(angle, resolution / 100)
        firmware = data[:7].decode("ascii").strip()
        baud = STATUS_BAUD_CODES[unpack_from("<H", data, 109 + shift)[0]]
    except (ValueError, KeyError) as exc:
        raise ProtocolError(
            "Unsupported status layout or configuration; preserve raw B1 for review"
        ) from exc
    if data[115 + shift] not in (0, 1):
        raise ProtocolError("Unsupported status measurement unit")
    return DeviceStatus(
        firmware,
        data[7],
        data[8],
        angle,
        resolution / 100,
        baud,
        "mm" if data[115 + shift] else "cm",
        data[95 + shift],
        bool(data[112 + shift]),
        data[113 + shift],
        data.hex(),
    )
