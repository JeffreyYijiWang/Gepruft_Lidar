"""Transparent TCP stream with optional independent leased bridge-control connection."""

import asyncio
import json
from typing import Any


class TCPTransport:
    def __init__(
        self,
        host: str,
        port: int,
        baud: int = 9600,
        control_port: int | None = None,
        token: str = "",
    ) -> None:
        self.host, self.port, self.baud = host, port, baud
        self.control_port, self.token = control_port, token
        self.can_set_baud = control_port is not None
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self.control_reader: asyncio.StreamReader | None = None
        self.control_writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()

    async def _control(self, command: dict[str, object]) -> dict[str, Any]:
        if self.control_writer is None or self.control_reader is None:
            raise OSError("Bridge control channel is not connected")
        async with self._lock:
            self.control_writer.write(json.dumps(command).encode() + b"\n")
            await self.control_writer.drain()
            line = await asyncio.wait_for(self.control_reader.readline(), 5)
            result: dict[str, Any] = json.loads(line)
            if not result.get("ok"):
                raise OSError("Bridge rejected control request (check token, lease, and baud)")
            return result

    async def open(self) -> None:
        try:
            port = self.port
            if self.control_port is not None:
                self.control_reader, self.control_writer = await asyncio.wait_for(
                    asyncio.open_connection(self.host, self.control_port, limit=4096), 5
                )
                lease = await self._control({"op": "lease", "token": self.token})
                port = int(lease["data_port"])
                self.baud = int(lease["baud"])
            self.reader, self.writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, port), 5
            )
        except BaseException:
            await self.close()
            raise

    async def read(self, size: int = 4096) -> bytes:
        if self.reader is None:
            raise EOFError("TCP connection closed")
        try:
            data = await asyncio.wait_for(self.reader.read(size), 0.1)
        except TimeoutError:
            return b""
        if not data:
            raise EOFError("Bridge disconnected")
        return data

    async def write(self, data: bytes) -> None:
        if self.writer is None:
            raise EOFError("TCP connection closed")
        self.writer.write(data)
        await asyncio.wait_for(self.writer.drain(), 5)

    async def set_baud(self, baud: int) -> None:
        if not self.can_set_baud:
            if baud != self.baud:
                raise ValueError("A transparent bridge without control supports fixed baud only")
            return
        result = await self._control({"op": "baud", "baud": baud})
        if result["baud"] != baud:
            raise OSError("Host adapter baud verification failed")
        self.baud = baud

    async def close(self) -> None:
        for writer in (self.writer, self.control_writer):
            if writer is not None:
                writer.close()
                try:
                    await writer.wait_closed()
                except OSError:
                    pass
        self.reader = self.writer = self.control_reader = self.control_writer = None
