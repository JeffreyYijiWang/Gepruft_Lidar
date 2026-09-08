"""Explicit opt-in original LMSAPI backend, isolated from the production device service."""

import argparse
import io
import json
import os
import subprocess
import threading
import uuid
import zipfile
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .lmsapi_check import REVIEWED_SHA256, digest, inspect_archive
from .protocol.framing import Frame, FrameCandidate, Framer
from .protocol.responses import ProtocolError, decode_status, response

DLL_SHA256 = "534f7b6fe9212f7592f409ccfafc94d7cd618cb3bb49175823e911186dad437c"
RUNNER_SOURCE = Path(__file__).with_name("native") / "LmsapiRunner.cs"
ACTIVE_SECONDS = 90  # Original retries are inside this bound; never retry the outer call.


def prepare(archive_path: Path, output: Path) -> dict[str, Any]:
    package = archive_path.read_bytes()
    if digest(package) != REVIEWED_SHA256:
        raise ValueError("Unreviewed LMSAPI archive; refusing to extract or execute")
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        listing = inspect_archive(archive)
        library = archive.read("lmsapi/libDLL/lmsapi.dll")
        notice = archive.read("lmsapi/docs/html/license.html")
    if digest(library) != DLL_SHA256:
        raise ValueError("Unexpected native DLL")
    compiler = Path(os.environ.get("SystemRoot", "C:/Windows")) / (
        "Microsoft.NET/Framework/v4.0.30319/csc.exe"
    )
    if os.name != "nt" or not compiler.is_file():
        raise ValueError("Native Windows .NET Framework compiler required; nothing installed")
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "lmsapi.dll").write_bytes(library)
    (output / "license.html").write_bytes(notice)
    source = RUNNER_SOURCE.read_bytes()
    (output / "LmsapiRunner.cs").write_bytes(source)
    executable = output / "LmsapiRunner.exe"
    command = [
        str(compiler),
        "/nologo",
        "/platform:x86",
        "/target:exe",
        "/optimize+",
        "/reference:System.Web.Extensions.dll",
        f"/out:{executable}",
        str(output / "LmsapiRunner.cs"),
    ]
    built = subprocess.run(command, cwd=output, capture_output=True, text=True, timeout=60)
    (output / "build-output.txt").write_text(built.stdout + built.stderr, encoding="utf-8")
    built.check_returncode()
    manifest = {
        "timestamp": datetime.now(UTC).isoformat(),
        "archive": str(archive_path.resolve()),
        "archive_sha256": REVIEWED_SHA256,
        "archive_entries": len(listing),
        "dll_sha256": DLL_SHA256,
        "runner_source_sha256": digest(source),
        "runner_sha256": digest(executable.read_bytes()),
        "build_command": command,
        "profile": {
            "port": "COM7",
            "baud": 9600,
            "width": 180,
            "resolution": 0.5,
            "range_metres": 8,
            "intensity": False,
            "original_dll_unchanged": True,
            "max_library_tries": 10,
        },
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def verify_bundle(bundle: Path) -> dict[str, Any]:
    manifest: dict[str, Any] = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    if digest((bundle / "lmsapi.dll").read_bytes()) != DLL_SHA256:
        raise ValueError("Original DLL was changed")
    if digest((bundle / "LmsapiRunner.exe").read_bytes()) != manifest["runner_sha256"]:
        raise ValueError("Runner was changed")
    if digest(RUNNER_SOURCE.read_bytes()) != manifest["runner_source_sha256"]:
        raise ValueError("Runner source changed; prepare a new bundle")
    return manifest


def validate_markers(paths: list[Path], log: Path) -> None:
    resolved = [p.resolve() for p in [*paths, log]]
    if len({str(p).casefold() for p in resolved}) != len(resolved):
        raise ValueError("Power, startup, cancel and log paths must differ")
    if any(p.exists() for p in resolved):
        raise ValueError("Confirmation, cancellation and log paths must be new")


def summarize(records: list[dict[str, Any]], returncode: int) -> dict[str, Any]:
    candidates: list[FrameCandidate] = []
    framer = Framer(candidates.append)
    raw = bytearray()
    for item in records:
        if item.get("event") == "rx" and item.get("phase") == "passive":
            chunk = bytes.fromhex(item["hex"])
            raw.extend(chunk)
            framer.feed(chunk)
    while framer.buffer:
        framer.expire()
    status = next((r for r in reversed(records) if r.get("event") == "status_result"), None)
    decoded, error = None, None
    if status is not None and status.get("library_success"):
        payload = bytes.fromhex(status["payload_hex"])
        try:
            # Decoder input only: header/footer are NOT reconstructed or presented as captured.
            decoded = asdict(decode_status(response(Frame(0x80, payload, b""))))
        except (ProtocolError, ValueError, IndexError) as exc:
            error = str(exc)
    return {
        "process_returncode": returncode,
        "library_connection_nonnull": any(
            r.get("event") == "connect_result" and r.get("connection_nonnull") for r in records
        ),
        "passive_rx_hex": raw.hex(" ").upper(),
        "passive_rx_bytes": len(raw),
        "passive_valid_frames": [
            {"hex": c.raw.hex(" ").upper(), "offset": c.offset, "crc": f"{c.crc_received:04X}"}
            for c in candidates
            if c.crc_valid
        ],
        "status_library_report": status,
        "status_decoded": decoded,
        "status_decode_error": error,
        "library_status_succeeded": returncode == 0 and decoded is not None,
        "active_tx_bytes": None,
        "active_rx_wire_bytes": None,
        "standalone_ack": None,
        "independently_captured_active_crc": None,
        "evidence_limit": "Original DLL hides active raw I/O; counts and ACK unavailable. "
        "Library status success is distinct from the normal guarded diagnostic.",
        "helper_exited": True,
    }


def run(
    bundle: Path, log: Path, markers: list[Path], *, physical: bool, allow_legacy: bool
) -> dict[str, Any]:
    if not physical or not allow_legacy:
        raise ValueError(
            "Explicit physical confirmation and legacy configuration/retry consent required"
        )
    if len(markers) != 3:
        raise ValueError("Three marker paths required")
    validate_markers(markers, log)
    manifest = verify_bundle(bundle)
    log.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str((bundle / "LmsapiRunner.exe").resolve()),
        "--run",
        "--physical-confirmed",
        "--allow-legacy-configuration-and-retries",
        *(str(p.resolve()) for p in markers),
    ]
    records: list[dict[str, Any]] = []
    run_id = str(uuid.uuid4())
    with log.open("x", encoding="utf-8") as stream:

        def emit(record: dict[str, Any]) -> None:
            record.update(run_id=run_id, backend="original-lmsapi-1.1c")
            record.setdefault("timestamp", datetime.now(UTC).isoformat())
            line = json.dumps(record, ensure_ascii=True)
            stream.write(line + "\n")
            stream.flush()
            print(line, flush=True)
            records.append(record)

        emit(
            {
                "event": "experiment_start",
                "manifest": manifest,
                "physical_connection": (
                    "Operator-confirmed Keyspan > black adapter > gray cable > LMS200"
                ),
                "legacy_configuration_and_retries_authorized": True,
            }
        )
        with subprocess.Popen(
            command,
            cwd=bundle,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8-sig",
            errors="replace",
            bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ) as process:
            # Whole-process fail-safe, including native crash/hang and native cleanup.
            timer = threading.Timer(710, process.kill)
            timer.daemon = True
            timer.start()
            try:
                assert process.stdout is not None
                for line in process.stdout:
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        record = {"event": "helper_output", "text": line.rstrip()}
                    emit(record)
                returncode = process.wait(timeout=5)
            except BaseException:
                process.kill()
                process.wait(timeout=5)
                emit(
                    {
                        "event": "helper_terminated",
                        "note": "No outer retry; settings may have changed",
                    }
                )
                raise
            finally:
                timer.cancel()
        result = summarize(records, returncode)
        emit({"event": "experiment_result", **result})
    return result


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description=__doc__)
    commands = cli.add_subparsers(dest="command", required=True)
    build = commands.add_parser(
        "prepare", help="Build the x86 host; no DLL execution or serial I/O"
    )
    build.add_argument("--archive", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    check = commands.add_parser(
        "self-test", help="Load original DLL and check CRC without serial I/O"
    )
    check.add_argument("--bundle", type=Path, required=True)
    active = commands.add_parser(
        "run", help="Explicitly allow original configuration and retry behavior"
    )
    active.add_argument("--bundle", type=Path, required=True)
    active.add_argument("--log", type=Path, required=True)
    active.add_argument("--power-on-file", type=Path, required=True)
    active.add_argument("--startup-complete-file", type=Path, required=True)
    active.add_argument("--cancel-file", type=Path, required=True)
    active.add_argument("--confirm-physical-setup", action="store_true")
    active.add_argument("--allow-legacy-configuration-and-retries", action="store_true")
    return cli


def main() -> None:
    cli = parser()
    args = cli.parse_args()
    if args.command == "prepare":
        print(json.dumps(prepare(args.archive, args.output), indent=2))
    elif args.command == "self-test":
        verify_bundle(args.bundle)
        result = subprocess.run(
            [str((args.bundle / "LmsapiRunner.exe").resolve()), "--self-test"],
            cwd=args.bundle,
            timeout=15,
            capture_output=True,
            text=True,
            encoding="utf-8-sig",
            errors="replace",
        )
        print(result.stdout, end="")
        print(result.stderr, end="")
        raise SystemExit(result.returncode)
    else:
        if not args.confirm_physical_setup or not args.allow_legacy_configuration_and_retries:
            cli.error("Physical confirmation and configuration/retry consent are both required")
        outcome = run(
            args.bundle,
            args.log,
            [args.power_on_file, args.startup_complete_file, args.cancel_file],
            physical=args.confirm_physical_setup,
            allow_legacy=args.allow_legacy_configuration_and_retries,
        )
        if not outcome["library_status_succeeded"]:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
