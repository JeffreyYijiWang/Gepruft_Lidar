"""Typed requests; sources and vectors are catalogued in docs/PROTOCOL.md."""

from dataclasses import dataclass
from enum import IntEnum
from struct import pack

from .framing import encode


class Mode(IntEnum):
    INSTALLATION = 0x00  # Listing §7.4.1, p40
    CONTINUOUS = 0x24  # p41: all values, complete scan
    ON_REQUEST = 0x25  # p41: stop continuous, default monitoring mode


BAUD_CODES = {9600: 0x42, 19200: 0x41, 38400: 0x40, 500000: 0x48}  # p44
STATUS_BAUD_CODES = {0x8067: 9600, 0x8033: 19200, 0x8019: 38400, 0x8001: 500000}


@dataclass(frozen=True)
class Command:
    name: str
    payload: bytes
    response_id: int
    timeout: float = 3.0
    attempts: int = 3
    mutates: bool = False

    def telegram(self, address: int = 0) -> bytes:
        if not 0 <= address <= 0x7F:
            raise ValueError("Scanner address must be 0..127")
        return encode(self.payload, address)


def status_request() -> Command:
    return Command("status", b"\x31", 0xB1)  # §7.6, p52


def type_request() -> Command:
    return Command("device type", b"\x3a", 0xBA)  # §7.15, p65


def configuration_request() -> Command:
    return Command("read configuration", b"\x74", 0xF4)  # §7.43, p90


def operating_mode(mode: Mode, password: str = "SICK_LMS") -> Command:
    parameter = bytes((mode,))
    if mode == Mode.INSTALLATION:
        if len(password) != 8 or not all(
            c.isascii() and (c.isalnum() or c == "_") for c in password
        ):
            raise ValueError(
                "Installation password must contain 8 ASCII letters/digits/underscores"
            )
        parameter += password.encode("ascii")
    return Command(f"mode {mode.name}", b"\x20" + parameter, 0xA0, mutates=True, attempts=1)


def baud_rate(baud: int) -> Command:
    if baud not in BAUD_CODES:
        raise ValueError("Unsupported LMS2xx baud rate")
    return Command("baud rate", bytes((0x20, BAUD_CODES[baud])), 0xA0, attempts=1, mutates=True)


def validate_geometry(angle: int, resolution: float) -> None:
    if angle not in (100, 180) or resolution not in (0.25, 0.5, 1.0):
        raise ValueError("Expected 100/180 degrees and 0.25/0.5/1 degree resolution")
    if resolution == 0.25 and angle != 100:
        raise ValueError("Standard 0.25 degree scans require a 100 degree field of view")


def variant(angle: int, resolution: float) -> Command:
    validate_geometry(angle, resolution)
    return Command(
        "scan variant",
        b"\x3b" + pack("<HH", angle, round(resolution * 100)),
        0xBB,
        attempts=1,
        mutates=True,
    )  # §7.16, p66


def write_configuration(data: bytes) -> Command:
    if len(data) not in (32, 34):
        raise ValueError("Only documented 32-byte legacy / 34-byte configuration supported")
    return Command(
        "write configuration", b"\x77" + data, 0xF7, timeout=8.0, attempts=1, mutates=True
    )  # setup C.6 p12: up to 7s
