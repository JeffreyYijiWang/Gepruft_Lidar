"""pyserial in bounded worker calls; no LMS parsing. 8-N-1, no flow control."""

import asyncio
import time

import serial
from serial.tools import list_ports


def ports() -> list[dict[str, str | int | None]]:
    return [
        {"device": p.device, "description": p.description, "vid": p.vid, "pid": p.pid}
        for p in list_ports.comports()
    ]


class SerialTransport:
    can_set_baud = True

    def __init__(self, port: str, baud: int = 9600) -> None:
        self.port = port
        self.baud = baud
        self.serial: serial.Serial | None = None
        self._write_lock = asyncio.Lock()

    async def open(self) -> None:
        self.serial = await asyncio.to_thread(
            serial.serial_for_url,
            self.port,
            baudrate=self.baud,
            bytesize=8,
            parity="N",
            stopbits=1,
            timeout=0.05,
            write_timeout=2,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        )

    def _device(self) -> serial.Serial:
        if self.serial is None or not self.serial.is_open:
            raise EOFError("Serial device closed")
        return self.serial

    async def read(self, size: int = 4096) -> bytes:
        device = self._device()
        # Reading all 4096 unconditionally adds a timeout to every short scan.
        return await asyncio.to_thread(device.read, max(1, min(size, device.in_waiting)))

    def _write(self, data: bytes) -> None:
        device = self._device()
        if self.baud == 500000:
            # Listing §4.3 p24: >=55us between host bytes, <=6ms. USB/OS timing
            # is hardware-qualified separately; never claim hard real-time guarantees.
            for value in data:
                if device.write(bytes((value,))) != 1:
                    raise OSError("Incomplete serial write")
                device.flush()
                time.sleep(0.0001)
        else:
            if device.write(data) != len(data):
                raise OSError("Incomplete serial write")
            device.flush()

    async def write(self, data: bytes) -> None:
        async with self._write_lock:
            await asyncio.to_thread(self._write, data)

    async def set_baud(self, baud: int) -> None:
        async with self._write_lock:
            device = self._device()
            await asyncio.to_thread(setattr, device, "baudrate", baud)
            self.baud = baud

    async def close(self) -> None:
        if self.serial is not None:
            await asyncio.to_thread(self.serial.close)
            self.serial = None
