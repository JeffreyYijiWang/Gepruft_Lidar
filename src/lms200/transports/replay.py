"""Replay raw scan streams using sidecar configuration and optional receive timing."""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO, TextIO


class ReplayTransport:
    can_set_baud = False

    def __init__(self, path: Path, speed: float = 1.0) -> None:
        self.path, self.speed = path, speed
        self.baud = 9600
        self.metadata: dict[str, Any] = {}
        self.file: BinaryIO | None = None
        self.index: TextIO | None = None
        self._remaining = 0
        self._previous_time: float | None = None
        self.timestamp: str | None = None

    async def open(self) -> None:
        metadata_path = self.path.with_suffix(".metadata.json")
        if not metadata_path.exists():
            raise ValueError("Raw replay needs a .metadata.json sidecar; see docs/PROTOCOL.md")
        self.metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if self.metadata.get("format") != "lms200-raw-v1":
            raise ValueError("Unsupported recording format")
        self.baud = int(self.metadata["baud"])
        self.file = self.path.open("rb")
        index_path = self.path.with_suffix(".index.jsonl")
        self.index = index_path.open(encoding="utf-8") if index_path.exists() else None
        self._remaining = 0
        self._previous_time = None

    async def read(self, size: int = 4096) -> bytes:
        if self.file is None:
            raise EOFError("Replay closed")
        if self.index is not None and self._remaining == 0:
            line = self.index.readline()
            if not line:
                if self.file.read(1):
                    raise ValueError("Recording contains data beyond its timing index")
                raise EOFError("Replay complete")
            item = json.loads(line)
            self._remaining = int(item["length"])
            if not 1 <= self._remaining <= 814 or int(item["offset"]) != self.file.tell():
                raise ValueError("Invalid recording index")
            self.timestamp = str(item["timestamp"])
            current_time = datetime.fromisoformat(self.timestamp).timestamp()
            if self._previous_time is not None:
                await asyncio.sleep(max(0, current_time - self._previous_time) / self.speed)
            self._previous_time = current_time
        else:
            await asyncio.sleep(0)
        amount = min(size, 137, self._remaining) if self.index is not None else min(size, 137)
        data = self.file.read(amount)
        if not data:
            if self.index is not None and self._remaining:
                raise ValueError("Recording ended inside an indexed telegram")
            raise EOFError("Replay complete")
        if self.index is not None:
            self._remaining -= len(data)
        return data

    async def write(self, data: bytes) -> None:
        raise ValueError("Replay cannot receive hardware commands")

    async def set_baud(self, baud: int) -> None:
        if baud != self.baud:
            raise ValueError("Replay baud rate is recording metadata")

    async def close(self) -> None:
        if self.file is not None:
            self.file.close()
            self.file = None
        if self.index is not None:
            self.index.close()
            self.index = None
