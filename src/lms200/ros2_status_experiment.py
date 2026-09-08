"""Native Windows COM7 owner for the opt-in ROS 2/LaViRIA status-only experiment."""

import argparse
import hashlib
import json
import os
import queue
import subprocess
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import serial

from .hardware_diagnostic import (
    SERIAL_CONFIG,
    STATUS_REQUEST,
    Capture,
    Journal,
    exception_details,
    flush_output,
    initial_state,
)

REPO = Path(__file__).resolve().parents[2]


class SingleStatusGate:
    """Accept one complete, exact status packet; never relay arbitrary node writes."""

    def __init__(self) -> None:
        self.buffer = bytearray()
        self.sent = False

    def accept(self, data: bytes, *, startup_authorized: bool) -> bytes | None:
        if not data:
            return None
        if not startup_authorized or self.sent:
            raise ValueError("Node TX before startup gate or after its single request")
        self.buffer.extend(data)
        if not STATUS_REQUEST.startswith(self.buffer):
            raise ValueError("Node attempted bytes outside the one-status allowance")
        if len(self.buffer) != len(STATUS_REQUEST):
            return None
        self.sent = True
        return bytes(self.buffer)


def verify_build() -> dict[str, Any]:
    manifest: dict[str, Any] = json.loads(
        (REPO / "tools/ros2_status/build-evidence.json").read_text()
    )
    for relative, expected in manifest["files"].items():
        path = (REPO / relative).resolve()
        if not path.is_relative_to(REPO):
            raise ValueError("Build manifest path escapes repository")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected["sha256"] or path.stat().st_size != expected["size"]:
            raise ValueError(f"Build input/artifact changed: {relative}")
    return manifest


def wsl_path(path: Path) -> str:
    path = path.resolve()
    if not path.drive or path.drive.startswith("\\"):
        raise ValueError("Expected a local Windows drive path")
    return "/mnt/" + path.drive[0].lower() + path.as_posix()[2:]


def run(log_dir: Path, *, confirmed: bool, already_powered_on: bool = False) -> dict[str, Any]:
    if not confirmed:
        state = "powered-on/startup-complete" if already_powered_on else "scanner-off"
        raise ValueError(
            f"Fresh {state}/direct-wiring/no-jumpers/closed-apps confirmation required"
        )
    if os.name != "nt":
        raise RuntimeError("The physical COM7 owner must run natively on Windows")
    manifest = verify_build()
    log_dir = log_dir.resolve()
    if not log_dir.is_relative_to(REPO / "docs/diagnostics"):
        raise ValueError("Run directory must be under docs/diagnostics")
    log_dir.mkdir(parents=False, exist_ok=False)
    (log_dir / "build-evidence.json").write_text(json.dumps(manifest, indent=2) + "\n")
    report: dict[str, Any] = {
        "serial_config": SERIAL_CONFIG,
        "ack": False,
        "nak": False,
        "telegrams": [],
        "write_count": None,
        "flush_completed": False,
        "port_closed": True,
        "start_mode": "already_powered_on" if already_powered_on else "passive_power_on",
        "confirmation_source": (
            "pre_run_powered_on_checklist" if already_powered_on else "operator_marker_files"
        ),
        "power_on_confirmed": already_powered_on,
        "startup_complete_confirmed": already_powered_on,
        "success": False,
        "error": None,
    }
    with (log_dir / "windows-raw.jsonl").open("x", encoding="utf-8") as output:
        journal = Journal(output, "ros2-laviria-status", "COM7")
        capture = Capture(journal, report)
        device = None
        process = None
        collector = None
        events: queue.Queue[dict[str, Any]] = queue.Queue()
        gate = SingleStatusGate()
        started = time.monotonic()
        power_on = None
        drained = None
        relay_ready = False
        ready = False
        status_authorized = False
        node_exit = None
        try:
            journal.emit(
                (
                    "operator_powered_on_checklist_confirmed"
                    if already_powered_on
                    else "operator_off_checklist_confirmed"
                ),
                chain="Keyspan directly to LMS200 RS232",
                start_mode=report["start_mode"],
            )
            process = subprocess.Popen(
                [
                    "wsl.exe",
                    "--distribution",
                    "Ubuntu-24.04",
                    "--exec",
                    "python3",
                    wsl_path(REPO / "tools/ros2_status/pty_relay.py"),
                    "--run-dir",
                    wsl_path(log_dir),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )

            def collect_events() -> None:
                assert process is not None and process.stdout is not None
                for line in process.stdout:
                    try:
                        event = json.loads(line)
                        if event.get("event") == "node_tx":
                            event["controller_status_trigger_seen"] = (
                                log_dir / "status.trigger"
                            ).exists()
                        events.put(event)
                    except ValueError:
                        events.put({"event": "relay_console", "text": line.rstrip()})

            collector = threading.Thread(target=collect_events, daemon=True)
            collector.start()
            device = serial.Serial(port=None, **SERIAL_CONFIG)
            device.port, device.dtr, device.rts = "COM7", False, False
            device.open()
            report["port_closed"] = False
            journal.emit("windows_listener_open", **initial_state(device))
            while time.monotonic() - started < 660:
                now = time.monotonic()
                if (log_dir / "cancel.trigger").exists():
                    raise InterruptedError("Operator cancelled")
                if not ready and relay_ready and (log_dir / "ros2.ready").exists():
                    ready = True
                    (log_dir / "listener.ready").touch(exist_ok=False)
                    journal.emit("both_listeners_ready", tx_bytes=0)
                if already_powered_on:
                    if not ready and now - started > 300:
                        raise TimeoutError("Both listeners were not ready in 300 seconds")
                else:
                    if ready and power_on is None and (log_dir / "power-on.confirmed").exists():
                        power_on = now
                        report["power_on_confirmed"] = True
                        journal.emit("operator_power_on_confirmed")
                    if power_on is not None and (log_dir / "startup-complete.confirmed").exists():
                        if not report["startup_complete_confirmed"]:
                            report["startup_complete_confirmed"] = True
                            journal.emit("operator_startup_complete_confirmed")
                        if not status_authorized and now - power_on >= 65:
                            capture.tx_boundary = len(capture.raw)
                            status_authorized = True
                            (log_dir / "status.trigger").touch(exist_ok=False)
                            journal.emit("status_authorized_after_startup", seconds=now - power_on)
                    if power_on is None and now - started > 300:
                        raise TimeoutError("No power-on confirmation in 300 seconds")
                    if power_on is not None and not status_authorized and now - power_on > 300:
                        raise TimeoutError("No startup-complete confirmation in 300 seconds")
                before = len(capture.raw)
                capture.read(device, "post_tx" if gate.sent else "passive")
                received = bytes(capture.raw[before:])
                if received and process.poll() is None:
                    assert process.stdin is not None
                    process.stdin.write(
                        json.dumps({"event": "serial_rx", "hex": received.hex()}) + "\n"
                    )
                    process.stdin.flush()
                if process.poll() is not None:
                    collector.join(timeout=1)
                while not events.empty():
                    event = events.get_nowait()
                    name = event.pop("event")
                    journal.emit("relay_" + name, **event)
                    if name == "relay_ready":
                        relay_ready = True
                    elif name == "node_exit":
                        node_exit = event["returncode"]
                    elif name == "relay_error":
                        raise OSError(event.get("error", "WSL relay error"))
                    elif name == "node_tx":
                        packet = gate.accept(
                            bytes.fromhex(event["hex"]),
                            startup_authorized=(
                                status_authorized
                                and event.get("controller_status_trigger_seen") is True
                            ),
                        )
                        if packet is not None:
                            capture.tx_boundary = len(capture.raw)
                            journal.emit(
                                "tx_attempt", count=len(packet), hex=packet.hex(" ").upper()
                            )
                            report["write_count"] = device.write(packet)
                            journal.emit("write_returned", count=report["write_count"])
                            if report["write_count"] != 7:
                                raise OSError("Short status write; do not retry")
                            flush_output(device)
                            report["flush_completed"] = True
                            drained = time.monotonic()
                            journal.emit("flush_completed", out_waiting=device.out_waiting)
                if already_powered_on and ready and not status_authorized:
                    # Preserve/forward ready-iteration pre-TX bytes and reject any
                    # queued early node traffic before creating the status trigger.
                    capture.tx_boundary = len(capture.raw)
                    (log_dir / "status.trigger").touch(exist_ok=False)
                    status_authorized = True
                    journal.emit("status_authorized_for_already_powered_on_scanner")
                if node_exit is not None or process.poll() is not None:
                    if drained is None:
                        raise OSError("ROS 2/relay exited before a complete status write and flush")
                    if drained is None or now - drained >= 5:
                        break
                if drained is not None and now - drained >= 8:
                    break
            else:
                raise TimeoutError("Overall 660-second deadline")
            if drained is not None:
                report["post_flush_read_seconds"] = time.monotonic() - drained
            report["node_exit_code"] = node_exit
            report["windows_status_valid"] = bool(
                capture.status is not None and not capture.post_nak
            )
            report["success"] = bool(report["windows_status_valid"] and node_exit == 0)
        except (Exception, KeyboardInterrupt) as exc:
            report["error"] = exception_details(exc)
            journal.emit("error", **report["error"])
        finally:
            if device is not None:
                try:
                    device.close()
                except Exception as exc:
                    report["close_error"] = exception_details(exc)
                report["port_closed"] = not device.is_open
            (log_dir / "cancel.trigger").touch(exist_ok=True)
            if process is not None:
                try:
                    process.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired as exc:
                        report["relay_cleanup_error"] = exception_details(exc)
                report["wsl_exit_code"] = process.returncode
                if collector is not None:
                    collector.join(timeout=1)
                for pipe in (process.stdin, process.stdout):
                    if pipe is not None:
                        pipe.close()
            report.update(
                rx_bytes=len(capture.raw),
                rx_hex=capture.raw.hex(" ").upper(),
                post_tx_ack=capture.post_ack,
                post_tx_nak=capture.post_nak,
                status=capture.status,
                startup=capture.startup,
                framing=asdict(capture.framer.stats),
                trailing_partial_hex=capture.framer.buffer.hex(" ").upper(),
                node_tx_hex=gate.buffer.hex(" ").upper(),
                partial_node_tx_hex="" if gate.sent else gate.buffer.hex(" ").upper(),
            )
            if not report["port_closed"] or report["error"] or report.get("relay_cleanup_error"):
                report["success"] = False
            journal.emit("result", **report)
            (log_dir / "windows-result.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--log-dir", type=Path)
    checklist = parser.add_mutually_exclusive_group()
    checklist.add_argument("--confirm-off-direct-checklist", action="store_true")
    checklist.add_argument(
        "--confirm-powered-on-direct-checklist",
        action="store_true",
        help="Fresh ON/startup-complete/direct-wiring/no-jumpers/closed-apps confirmation",
    )
    args = parser.parse_args()
    if not args.run:
        print(json.dumps({"offline_review_only": True, "verified_build": verify_build()}, indent=2))
        return
    if args.log_dir is None:
        parser.error("--log-dir must name a new diagnostics directory")
    result = run(
        args.log_dir,
        confirmed=args.confirm_off_direct_checklist or args.confirm_powered_on_direct_checklist,
        already_powered_on=args.confirm_powered_on_direct_checklist,
    )
    raise SystemExit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
