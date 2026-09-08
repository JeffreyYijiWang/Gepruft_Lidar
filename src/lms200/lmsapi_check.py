"""Offline comparison with reviewed LMSAPI 1.1c CRC source; never opens a port.

Builds only lmsapi_crc.c, with a small modern header, using native Windows GCC.
The full library, serial code, sensor code and demos are never loaded or built.
Third-party source and build products belong in ignored third_party/lmsapi/.
"""

import argparse
import ctypes
import hashlib
import io
import json
import os
import random
import shutil
import stat
import subprocess
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from .protocol.crc import crc16
from .protocol.framing import FrameCandidate, Framer

# Identity of the operator-supplied ZIP reviewed on 2026-09-07; not a vendor signature.
REVIEWED_SHA256 = "c8d2b5c38cc497f0ea7032e2c73a689c9bb52846497afdb4809ebf81d4898434"
CRC_SOURCE = "lmsapi/src/lmsapi_crc.c"
HEADER = """/* Local ABI header for an isolated CRC-only build, not the LMSAPI serial API. */
#include <stdint.h>
#include <stddef.h>
#define MAKEUINT16(lo, hi) ((((uint16_t)(hi)) << 8) | ((uint16_t)(lo)))
__declspec(dllexport) unsigned short lmsapi_create_crc(uint8_t *data, size_t len);
"""
# Published SICK Quick Manual (June 2001), C.2 p9. No fixture is transmitted.
GOLDEN = {
    "manual_status_request": bytes.fromhex("02 00 01 00 31 15 12"),
    "manual_startup": bytes.fromhex(
        "02 81 17 00 90 4C 4D 53 32 30 30 3B 33 30 31 30 36 33 3B 56 30 32 2E 30 36 20 13 64 5A"
    ),
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def inspect_archive(archive: zipfile.ZipFile) -> list[dict[str, Any]]:
    """Inspect all entries before extracting the single reviewed C source file."""
    seen: set[str] = set()
    inventory = []
    for entry in archive.infolist():
        path = PurePosixPath(entry.filename.replace("\\", "/"))
        name = str(path).casefold()
        if (
            path.is_absolute()
            or ".." in path.parts
            or ":" in str(path)
            or not path.parts
            or path.parts[0] != "lmsapi"
            or name in seen
            or stat.S_ISLNK(entry.external_attr >> 16)
        ):
            raise ValueError(f"Unsafe/duplicate archive entry: {entry.filename}")
        seen.add(name)
        inventory.append({"name": entry.filename, "bytes": entry.file_size})
    return inventory


def compare(crc: Callable[[bytes], int]) -> dict[str, Any]:
    published = []
    for label, frame in GOLDEN.items():
        upstream, local = crc(frame[:-2]), crc16(frame[:-2])
        expected = int.from_bytes(frame[-2:], "little")
        published.append(
            {
                "name": label,
                "frame_hex": frame.hex(" ").upper(),
                "lmsapi_crc": upstream,
                "project_crc": local,
                "published_crc": expected,
                "match": upstream == local == expected,
            }
        )
    # Deterministic synthetic differential inputs, not hardware observations.
    rng = random.Random(200)
    vectors = [b"", *(bytes([n]) for n in range(256))]
    vectors += [rng.randbytes(n) for n in (2, 3, 4, 5, 23, 146, 152, 808, 812)]
    vectors += [rng.randbytes(rng.randrange(813)) for _ in range(256)]
    failures = [i for i, data in enumerate(vectors) if crc(data) != crc16(data)]
    return {
        "published": published,
        "synthetic_vectors": len(vectors),
        "synthetic_mismatch_indices": failures,
        "passed": not failures and all(item["match"] for item in published),
    }


def check_capture(path: Path, crc: Callable[[bytes], int]) -> dict[str, Any]:
    """Re-read saved RX only; retain run/phase boundaries and reject noise as frames."""
    contents = path.read_bytes()
    streams: dict[tuple[str, str], bytearray] = {}
    for line in contents.splitlines():
        record = json.loads(line)
        if record.get("event") == "rx":
            key = (record["run_id"], record.get("phase", "unspecified"))
            streams.setdefault(key, bytearray()).extend(bytes.fromhex(record["hex"]))
    results = []
    for (run, phase), raw in streams.items():
        candidates: list[FrameCandidate] = []
        framer = Framer(candidates.append)
        framer.feed(bytes(raw))
        # Offline rescan at end-of-file, with no effect on original logs.
        while framer.buffer:
            framer.expire()
        frames = []
        for candidate in candidates:
            upstream = crc(candidate.raw[:-2])
            frames.append(
                {
                    "offset": candidate.offset,
                    "hex": candidate.raw.hex(" ").upper(),
                    "lmsapi_crc": upstream,
                    "wire_crc": candidate.crc_received,
                    "crc_valid": upstream == candidate.crc_received,
                    "matches_project": upstream == candidate.crc_expected,
                }
            )
        results.append(
            {
                "run_id": run,
                "phase": phase,
                "rx_bytes": len(raw),
                "rx_hex": raw.hex(" ").upper(),
                "complete_candidates": frames,
                "valid_frames": sum(1 for frame in frames if frame["crc_valid"]),
            }
        )
    return {
        "path": str(path.resolve()),
        "sha256": digest(contents),
        "streams": results,
        "parser": "project Framer; candidate CRC independently checked by LMSAPI",
    }


def run(archive_path: Path, workdir: Path, compiler: str, captures: list[Path]) -> dict[str, Any]:
    package = archive_path.read_bytes()
    if digest(package) != REVIEWED_SHA256:
        raise ValueError("ZIP differs from the reviewed LMSAPI 1.1c; inspect it before execution")
    if os.name != "nt":
        raise ValueError("This optional check builds a native Windows DLL; do not use Docker")
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        inventory = inspect_archive(archive)
        source = archive.read(CRC_SOURCE)
    compiler_path = shutil.which(compiler)
    if compiler_path is None:
        raise ValueError("Native GCC was not found; no dependency was installed")
    workdir = workdir.resolve()
    workdir.mkdir(parents=True, exist_ok=False)  # Never overwrite a previous build or evidence.
    (workdir / "lmsapi_1.1c.zip").write_bytes(package)
    (workdir / "archive-listing.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    (workdir / "lmsapi_crc.c").write_bytes(source)  # Original bytes and BSD notice preserved.
    (workdir / "lmsapi_crc.h").write_text(HEADER, encoding="utf-8")
    library = workdir / "lmsapi_crc_only.dll"
    command = [
        compiler_path,
        "-shared",
        "-O2",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-static-libgcc",
        "lmsapi_crc.c",
        "-o",
        library.name,
    ]
    build = subprocess.run(command, cwd=workdir, capture_output=True, text=True, timeout=60)
    (workdir / "build.json").write_text(
        json.dumps(
            {
                "command": command,
                "returncode": build.returncode,
                "stdout": build.stdout,
                "stderr": build.stderr,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    build.check_returncode()
    # The just-built library contains only the reviewed pure CRC source + compiler runtime.
    native = ctypes.CDLL(str(library))
    function = native.lmsapi_create_crc
    function.argtypes = [ctypes.POINTER(ctypes.c_ubyte), ctypes.c_size_t]
    function.restype = ctypes.c_ushort

    def calculate(data: bytes) -> int:
        buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        return int(function(buffer, len(data)))

    report = {
        "timestamp": datetime.now(UTC).isoformat(),
        "mode": "offline_lmsapi_crc_comparison",
        "serial_opened": False,
        "bytes_transmitted": 0,
        "software": "LMSAPI 1.1c CRC-only rebuild; not the full demo or serial backend",
        "source_url": "https://sourceforge.net/projects/lmsapi/files/",
        "input_archive": str(archive_path.resolve()),
        "archive_sha256": digest(package),
        "archive_bytes": len(package),
        "archive_entries": len(inventory),
        "source_sha256": digest(source),
        "header_sha256": digest(HEADER.encode()),
        "library": str(library),
        "library_sha256": digest(library.read_bytes()),
        "python_bits": ctypes.sizeof(ctypes.c_void_p) * 8,
        "comparison": compare(calculate),
        "saved_captures": [check_capture(path, calculate) for path in captures],
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--workdir", type=Path, required=True, help="New ignored build directory")
    parser.add_argument("--report", type=Path, required=True, help="New evidence JSON file")
    parser.add_argument("--compiler", default="gcc")
    parser.add_argument("--capture", type=Path, action="append", default=[])
    args = parser.parse_args()
    if args.report.exists():
        parser.error("Report already exists; preserve it and choose a new path")
    report = run(args.archive, args.workdir, args.compiler, args.capture)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps(report, indent=2))
    if not report["comparison"]["passed"] or any(
        not frame["matches_project"]
        for capture in report["saved_captures"]
        for run_result in capture["streams"]
        for frame in run_result["complete_candidates"]
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
