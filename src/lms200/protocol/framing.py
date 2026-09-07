"""Incremental LMS framing, Listing §4.2 pp21–24. No I/O here."""

from dataclasses import dataclass
from enum import IntEnum

from .crc import crc16

STX = 0x02
# p22: 812 bytes before optional indices. Table 7-25 p49 adds two real-time bytes.
MAX_PAYLOAD = 808  # 401 distances + count(2) + command/status(2) + indices(2).


class Control(IntEnum):
    ACK = 0x06
    NAK = 0x15


@dataclass(frozen=True)
class Frame:
    address: int
    payload: bytes
    raw: bytes

    @property
    def command(self) -> int:
        return self.payload[0]


@dataclass
class FrameStats:
    frames: int = 0
    crc_errors: int = 0
    invalid_lengths: int = 0
    noise_bytes: int = 0
    truncated_frames: int = 0


def encode(payload: bytes, address: int = 0) -> bytes:
    if not 0 <= address <= 255 or not 1 <= len(payload) <= MAX_PAYLOAD:
        raise ValueError("Invalid address or payload length")
    message = bytes((STX, address)) + len(payload).to_bytes(2, "little") + payload
    return message + crc16(message).to_bytes(2, "little")


class Framer:
    def __init__(self) -> None:
        self.buffer = bytearray()
        self.stats = FrameStats()

    def feed(self, data: bytes) -> list[Frame | Control]:
        self.buffer.extend(data)
        events: list[Frame | Control] = []
        while self.buffer:
            first = self.buffer[0]
            if first in (Control.ACK, Control.NAK):
                events.append(Control(first))
                del self.buffer[0]
                continue
            if first != STX:
                self.stats.noise_bytes += 1
                del self.buffer[0]
                continue
            if len(self.buffer) < 4:
                break
            length = int.from_bytes(self.buffer[2:4], "little")
            if not 1 <= length <= MAX_PAYLOAD:
                self.stats.invalid_lengths += 1
                del self.buffer[0]
                continue
            total = length + 6
            if len(self.buffer) < total:
                break
            raw = bytes(self.buffer[:total])
            if crc16(raw[:-2]) != int.from_bytes(raw[-2:], "little"):
                self.stats.crc_errors += 1
                del self.buffer[0]  # Rescan; embedded STX is only trusted after CRC validation.
                continue
            events.append(Frame(raw[1], raw[4:-2], raw))
            self.stats.frames += 1
            del self.buffer[:total]
        return events

    def expire(self) -> list[Frame | Control]:
        """Caller detected a stale incomplete frame; recover any valid frames behind it."""
        if not self.buffer:
            return []
        self.stats.truncated_frames += 1
        del self.buffer[0]
        return self.feed(b"")

    def reset(self) -> None:
        self.buffer.clear()
