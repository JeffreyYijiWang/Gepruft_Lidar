"""Synthetic LMS200 model. Response bytes are derived from documented field layouts.

Not a hardware capture or independent proof of hardware compatibility.
"""

import asyncio
from contextlib import suppress
from math import cos, radians, sin
from struct import pack, pack_into

from lms200.protocol.commands import BAUD_CODES, STATUS_BAUD_CODES, validate_geometry
from lms200.protocol.framing import Control, Frame, Framer, encode
from lms200.protocol.responses import Configuration


def default_configuration() -> Configuration:
    # Listing pp96–102, blocks A–A4. Synthetic explicit named defaults; no canned command.
    data = bytearray(34)
    data[2] = 0x46  # stop threshold, block B
    data[5:7] = bytes((2, 1))  # field A/B/C distance mode; mm
    data[9:12] = bytes((2, 2, 2))  # evaluation count, restart, restart time
    for offset in (14, 19, 24):  # contour tolerances/start/end, blocks M–P, R–U, W–Z
        data[offset : offset + 4] = bytes((10, 10, 80, 100))
    data[32] = 2  # dazzle evaluation count, block A4
    return Configuration(bytes(data))


class SimulatorTransport:
    can_set_baud = True

    def __init__(self, baud: int = 9600, device_baud: int = 9600, realtime: bool = True) -> None:
        self.baud, self.device_baud = baud, device_baud
        self.realtime = realtime
        self.angle, self.resolution = 180, 0.5
        self.config = default_configuration()
        self.mode = 0x25
        self.status = 0x10
        self.commands: list[bytes] = []
        self.nak_next = 0
        self.silence_next = 0
        self.omit_ack = False
        self.response_delay = 0.0
        self._incoming = Framer()
        self._queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=2048)
        self._pending = bytearray()
        self._producer: asyncio.Task[None] | None = None
        self._emit_lock = asyncio.Lock()
        self._scan_index = self._telegram_index = 0

    async def open(self) -> None:
        self._queue = asyncio.Queue(maxsize=2048)
        self._pending.clear()
        self._producer = asyncio.create_task(self._produce())

    async def read(self, size: int = 4096) -> bytes:
        if self._producer is None:
            raise EOFError("Simulator closed")
        if not self._pending:
            try:
                self._pending.extend(await asyncio.wait_for(self._queue.get(), 0.05))
            except TimeoutError:
                return b""
        result = bytes(self._pending[:size])
        del self._pending[:size]
        return result

    async def _emit(self, data: bytes) -> None:
        async with self._emit_lock:
            # Deterministic fragmentation, including split headers and CRCs.
            pos = 0
            for step in (1, 2, 7, 31, 128):
                if pos >= len(data):
                    return
                await self._queue.put(data[pos : pos + step])
                pos += step
            if pos < len(data):
                await self._queue.put(data[pos:])

    def status_data(self) -> bytes:
        # 152-byte wire layout: Listing Table 7-34, corrected reserved block D width
        # corroborated by SICK Toolbox _getSickStatus (see docs/PROTOCOL.md).
        data = bytearray(152)
        data[:7] = b"V02.10 "
        data[7] = self.mode
        data[8] = int((self.status & 7) >= 3)
        data[101] = self.config.mode
        pack_into("<HH", data, 106, self.angle, round(self.resolution * 100))
        pack_into(
            "<H", data, 115, next(k for k, v in STATUS_BAUD_CODES.items() if v == self.device_baud)
        )
        data[121] = int(self.config.unit == "mm")
        data[123:130] = b"V02.10 "
        return bytes(data)

    async def write(self, data: bytes) -> None:
        if self.baud != self.device_baud:
            return
        for frame in self._incoming.feed(data):
            if not isinstance(frame, Frame) or frame.address not in (0, 1):
                continue
            self.commands.append(frame.payload)
            if self.silence_next:
                self.silence_next -= 1
                continue
            if self.nak_next:
                self.nak_next -= 1
                await self._emit(bytes((Control.NAK,)))
                continue
            payload = frame.payload
            result = b"\x92"
            new_baud = None
            if payload == b"\x31":
                result = b"\xb1" + self.status_data()
            elif payload == b"\x3a":
                result = b"\xbaLMS200;301063;V02.10 "
            elif payload == b"\x74":
                result = b"\xf4" + self.config.raw
            elif payload[:1] == b"\x20" and len(payload) >= 2:
                code = payload[1]
                if code == 0 and payload[2:] == b"SICK_LMS":
                    self.mode = 0
                    result = b"\xa0\x00"
                elif code in (0x24, 0x25) and len(payload) == 2:
                    self.mode = code
                    result = b"\xa0\x00"
                elif code in BAUD_CODES.values() and len(payload) == 2:
                    new_baud = next(b for b, c in BAUD_CODES.items() if c == code)
                    result = b"\xa0\x00"
                else:
                    result = b"\xa0\x01"
            elif payload[:1] == b"\x3b" and len(payload) == 5 and self.mode in (0, 0x25):
                angle = int.from_bytes(payload[1:3], "little")
                resolution = int.from_bytes(payload[3:5], "little") / 100
                try:
                    validate_geometry(angle, resolution)
                    self.angle, self.resolution = angle, resolution
                    result = b"\xbb\x01" + payload[1:]
                except ValueError:
                    result = b"\xbb\x00" + payload[1:]
            elif payload[:1] == b"\x77" and len(payload) in (33, 35) and self.mode == 0:
                self.config = Configuration(payload[1:])
                result = b"\xf7\x01" + self.config.raw
            if not self.omit_ack:
                await self._emit(bytes((Control.ACK,)))
            await asyncio.sleep(self.response_delay)
            await self._emit(encode(result + bytes((self.status,)), 0x81))
            if new_baud is not None:
                self.device_baud = new_baud

    def scan_bytes(self) -> bytes:
        count = round(self.angle / self.resolution) + 1
        header = count | (0x4000 if self.config.unit == "mm" else 0)
        data = bytearray(b"\xb0" + pack("<H", header))
        phase = self._telegram_index / 30
        for index in range(count):
            theta = radians((180 - self.angle) / 2 + index * self.resolution)
            # Synthetic room contour with a moving rounded object.
            distance_m = 3.8 + 1.1 * sin(3 * theta + phase) + 0.35 * cos(7 * theta)
            value = round(distance_m * (1000 if self.config.unit == "mm" else 100))
            data.extend(pack("<H", value))
        if self.config.indices:
            data.extend((self._scan_index, self._telegram_index))
        self._scan_index = (self._scan_index + round(1 / self.resolution)) % 256
        self._telegram_index = (self._telegram_index + 1) % 256
        return encode(bytes(data) + bytes((self.status,)), 0x81)

    async def _produce(self) -> None:
        while True:
            if self.mode == 0x24 and self.baud == self.device_baud:
                raw = self.scan_bytes()
                await self._emit(raw)
                period = max(1 / (75 * self.resolution), len(raw) * 10 / self.baud)
                await asyncio.sleep(period if self.realtime else 0.01)
            else:
                await asyncio.sleep(0.005)

    async def set_baud(self, baud: int) -> None:
        self.baud = baud

    async def close(self) -> None:
        if self._producer is not None:
            self._producer.cancel()
            with suppress(asyncio.CancelledError):
                await self._producer
            self._producer = None
