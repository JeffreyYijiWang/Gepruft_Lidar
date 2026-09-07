"""Standard B0 scans: Listing §7.5 pp47–51, §7.46 p98, §10.8 p124."""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from math import cos, radians, sin
from struct import unpack_from
from typing import Any

from .commands import validate_geometry
from .responses import Configuration, ProtocolError, Response, StatusByte

OVERFLOW = {
    0x1FFF: "invalid_no_return",
    0x1FFE: "dazzling",
    0x1FFD: "operation_overflow",
    0x1FFB: "low_signal",
    0x1FFA: "channel_error",
    0x1FF7: "above_maximum",
}


@dataclass(frozen=True)
class Point:
    angle_deg: float
    raw: int
    distance_raw: int
    distance_m: float | None
    x: float | None
    y: float | None
    flags: tuple[str, ...]


@dataclass(frozen=True)
class Scan:
    timestamp: str
    sequence: int
    status: StatusByte
    field_of_view: int
    resolution: float
    count: int
    starting_angle: float
    angle_increment: float
    unit: str
    measuring_mode: int
    scan_index: int | None
    telegram_index: int | None
    points: tuple[Point, ...]
    raw_telegram_hex: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def decode_scan(
    reply: Response,
    angle: int,
    resolution: float,
    config: Configuration,
    sequence: int,
    timestamp: str | None = None,
) -> Scan:
    validate_geometry(angle, resolution)
    if reply.command != 0xB0 or len(reply.data) < 2:
        raise ProtocolError("Expected B0 measurement telegram")
    if config.mode not in (0, 1, 2):
        raise ProtocolError("Only documented 13-bit distance modes 00/01/02 are supported")
    header = unpack_from("<H", reply.data)[0]
    if header & 0x3C00:  # reserved bit10, raster bits11/12, partial scan bit13
        raise ProtocolError("Partial/interlaced or reserved scan header is unsupported")
    unit_code = header >> 14
    if unit_code not in (0, 1):
        raise ProtocolError("Reserved scan unit")
    unit = "mm" if unit_code else "cm"
    if unit != config.unit:
        raise ProtocolError("Scan unit disagrees with verified configuration")
    count = header & 0x03FF
    if count != round(angle / resolution) + 1:
        raise ProtocolError("Scan count disagrees with verified geometry")
    size = 2 + count * 2
    if len(reply.data) != size + (2 if config.indices else 0):
        raise ProtocolError(
            "Measurement length or real-time index layout disagrees with configuration"
        )
    start = (180 - angle) / 2  # p48: 100-degree field is physically 40..140 degrees.
    scale = 0.001 if unit == "mm" else 0.01
    points: list[Point] = []
    for index in range(count):
        raw = unpack_from("<H", reply.data, 2 + index * 2)[0]
        distance = raw & 0x1FFF
        flags: list[str] = []
        if config.mode in (0, 2):
            for mask, label in (
                (0x2000, "field_a"),
                (0x4000, "field_b"),
                (0x8000, "dazzling" if config.mode == 0 else "field_c"),
            ):
                if raw & mask:
                    flags.append(label)
        else:
            flags.append(f"reflector_level_{raw >> 13}")
        if distance in OVERFLOW:
            flags.append(OVERFLOW[distance])
        elif distance >= 0x1FF7:
            flags.append("reserved_special_value")
        valid = distance < 0x1FF7 and "dazzling" not in flags
        meters = distance * scale if valid else None
        theta = start + index * resolution
        points.append(
            Point(
                theta,
                raw,
                distance,
                meters,
                meters * cos(radians(theta)) if meters is not None else None,
                meters * sin(radians(theta)) if meters is not None else None,
                tuple(flags),
            )
        )
    return Scan(
        timestamp or datetime.now(UTC).isoformat(),
        sequence,
        reply.status,
        angle,
        resolution,
        count,
        start,
        resolution,
        unit,
        config.mode,
        reply.data[size] if config.indices else None,
        reply.data[size + 1] if config.indices else None,
        tuple(points),
        reply.frame.raw.hex(),
    )
