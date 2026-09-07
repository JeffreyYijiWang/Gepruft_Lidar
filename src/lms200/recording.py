"""Lossless raw telegrams plus metadata, timing index, and optional decoded JSONL."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from lms200.protocol.measurements import Scan


class Recorder:
    def __init__(
        self, directory: Path, metadata: dict[str, Any], name: str | None = None, jsonl: bool = True
    ) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.name = name or datetime.now(UTC).strftime("scan-%Y%m%dT%H%M%S-%fZ")
        if Path(self.name).name != self.name or self.name in ("", ".", ".."):
            raise ValueError("Recording name must be a filename stem")
        self.path = directory / (self.name + ".bin")
        self.raw = self.path.open("xb")
        self.index = self.path.with_suffix(".index.jsonl").open("x", encoding="utf-8")
        self.decoded: TextIO | None = None
        if jsonl:
            self.decoded = self.path.with_suffix(".jsonl").open("x", encoding="utf-8")
        self.metadata = {
            "format": "lms200-raw-v1",
            "created": datetime.now(UTC).isoformat(),
            "coordinate_frame": "x right, y forward, metres; CCW from right (top view)",
            **metadata,
        }
        self.path.with_suffix(".metadata.json").write_text(
            json.dumps(self.metadata, indent=2), encoding="utf-8"
        )
        self.count = 0
        self.closed = False

    def write(self, scan: Scan) -> None:
        if self.closed:
            raise ValueError("Recording is closed")
        raw = bytes.fromhex(scan.raw_telegram_hex)
        offset = self.raw.tell()
        self.raw.write(raw)
        self.index.write(
            json.dumps(
                {
                    "offset": offset,
                    "length": len(raw),
                    "timestamp": scan.timestamp,
                    "sequence": scan.sequence,
                }
            )
            + "\n"
        )
        if self.decoded is not None:
            self.decoded.write(
                json.dumps(
                    {"metadata": self.metadata, "scan": scan.to_dict()},
                    separators=(",", ":"),
                    allow_nan=False,
                )
                + "\n"
            )
        self.count += 1
        self.raw.flush()
        self.index.flush()
        if self.decoded is not None:
            self.decoded.flush()

    def close(self) -> None:
        if not self.closed:
            self.raw.close()
            self.index.close()
            if self.decoded is not None:
                self.decoded.close()
            self.closed = True
