"""Native, bounded RS-232 evidence capture; see docs/HARDWARE_DIAGNOSTIC.md.

Single-request modes retain their bounds; explicitly authorized status-repeat sends at
most ten read-only requests. Loopback requires isolation. Startup capture never writes.
"""

import argparse
import json
import math
import os
import signal
import sys
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO, TextIO

import serial
from serial.tools import list_ports

from .protocol.crc import crc16
from .protocol.framing import Control, Frame, FrameCandidate, Framer
from .protocol.responses import ProtocolError, decode_status, response
from .windows_serial_state import verify_windows_serial

STATUS_REQUEST = bytes.fromhex("02 00 01 00 31 15 12")  # QM p9; TL Table 7-31 p52.
LOOPBACK_PATTERN = bytes.fromhex("55 AA 00 FF 11 13 06 15 02 7E 80 01 FE A5 5A")
SERIAL_CONFIG: dict[str, Any] = {
    "baudrate": 9600,
    "bytesize": 8,
    "parity": "N",
    "stopbits": 1,
    "xonxoff": False,
    "rtscts": False,
    "dsrdtr": False,
    "timeout": 0.05,
    "write_timeout": 1.0,
}
READY_SECONDS = 300.0  # Operator preparation bound; not a scanner specification.
STARTUP_SECONDS = 65.0  # TL p38: <=60 s; five seconds of host margin.
STATUS_SECONDS = 3.0
DIRECT_STATUS_SECONDS = 5.0
FLUSH_SECONDS = 1.0


def exception_details(exc: BaseException) -> dict[str, Any]:
    return {
        "type": type(exc).__name__,
        "message": str(exc),
        "repr": repr(exc),
        "errno": getattr(exc, "errno", None),
        "winerror": getattr(exc, "winerror", None),
    }


class Journal:
    def __init__(self, stream: TextIO, mode: str, port: str | None) -> None:
        self.stream, self.mode, self.port = stream, mode, port
        self.run_id = str(uuid.uuid4())

    def emit(self, event: str, **values: Any) -> None:
        line = json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "monotonic_seconds": time.monotonic_ns() / 1_000_000_000,
                "run_id": self.run_id,
                "pid": os.getpid(),
                "mode": self.mode,
                "port": self.port,
                "event": event,
                **values,
            }
        )
        self.stream.write(line + "\n")
        self.stream.flush()
        print(line, flush=True)


class Capture:
    def __init__(
        self, journal: Journal, report: dict[str, Any], raw_stream: BinaryIO | None = None
    ) -> None:
        self.journal, self.report = journal, report
        self.raw_stream = raw_stream
        self.raw = bytearray()
        self.valid_candidates: deque[dict[str, Any]] = deque()
        self.framer = Framer(self.candidate)
        self.tx_boundary: int | None = None
        self.post_ack = False
        self.post_nak = False
        self.status: dict[str, Any] | None = None
        self.startup: dict[str, Any] | None = None
        self.scanner_response_frames = 0

    def candidate(self, candidate: FrameCandidate) -> None:
        raw = candidate.raw
        detail = {
            "offset_start": candidate.offset,
            "offset_end": candidate.offset + len(raw),
            "length": len(raw),
            "payload_length": int.from_bytes(raw[2:4], "little"),
            "address_hex": f"{raw[1]:02X}",
            "command_hex": f"{raw[4]:02X}",
            "hex": raw.hex(" ").upper(),
            "crc_expected": f"{candidate.crc_expected:04X}",
            "crc_received": f"{candidate.crc_received:04X}",
            "crc_valid": candidate.crc_valid,
        }
        self.report["telegrams"].append(detail)
        self.journal.emit("telegram_candidate", **detail)
        if candidate.crc_valid:
            self.valid_candidates.append(detail)

    def process(self, events: list[Frame | Control], phase: str) -> None:
        for event in events:
            if isinstance(event, Control):
                name = event.name.lower()
                self.report[name] = True
                if phase == "post_tx":
                    self.post_ack |= event == Control.ACK
                    self.post_nak |= event == Control.NAK
                self.journal.emit("control", name=event.name, hex=f"{event:02X}", phase=phase)
                continue
            detail = self.valid_candidates.popleft()
            try:
                reply = response(event)
                self.scanner_response_frames += 1
                detail["status_byte"] = asdict(reply.status)
                if reply.command == 0x90:
                    if len(event.payload) != 23 or not reply.data.startswith(b"LMS200;"):
                        raise ProtocolError("90h is not the documented LMS200 startup layout")
                    detail["identity"] = reply.data.decode("ascii").strip()
                    self.startup = detail
                    self.journal.emit("startup_validated", **detail)
                elif reply.command == 0xB1:
                    detail["decoded_status"] = asdict(decode_status(reply))
                    detail["preceding_post_tx_ack"] = self.post_ack
                    if (
                        self.tx_boundary is not None
                        and detail["offset_start"] >= self.tx_boundary
                        and self.post_ack
                    ):
                        self.status = detail
                    self.journal.emit("status_decoded", **detail)
            except (ProtocolError, UnicodeError) as exc:
                detail["decode_error"] = exception_details(exc)
                self.journal.emit("protocol_error", **detail["decode_error"])

    def read(self, device: serial.Serial, phase: str, *, framed: bool = True) -> None:
        data = device.read(max(1, min(4096, device.in_waiting)))
        if data:
            offset = len(self.raw)
            self.raw.extend(data)
            if self.raw_stream is not None:
                self.raw_stream.write(data)
                self.raw_stream.flush()
            self.journal.emit(
                "rx", offset=offset, count=len(data), hex=data.hex(" ").upper(), phase=phase
            )
            if framed:
                self.process(self.framer.feed(data), phase)
        # An empty/short read is not a telegram boundary. Preserve partial framing
        # across every read until the caller's overall capture deadline. The final
        # report retains any incomplete suffix; do not expire it on an idle gap.


def flush_output(device: serial.Serial) -> None:
    """Call pyserial flush, closing only our handle if its queue never drains."""
    expired = threading.Event()

    def abort() -> None:
        expired.set()
        device.close()

    timer = threading.Timer(FLUSH_SECONDS, abort)
    timer.daemon = True
    timer.start()
    try:
        device.flush()
    finally:
        timer.cancel()
        timer.join()
    if expired.is_set():
        raise TimeoutError("Output flush exceeded one second; own serial handle closed")


def initial_state(device: serial.Serial) -> dict[str, Any]:
    state: dict[str, Any] = {
        "settings": device.get_settings(),
        "dtr": device.dtr,
        "rts": device.rts,
        "is_open": device.is_open,
    }
    for name in ("cts", "dsr", "ri", "cd", "in_waiting", "out_waiting"):
        try:
            state[name] = getattr(device, name)
        except OSError as exc:
            state[name] = exception_details(exc)
    return state


def run_diagnostic(
    mode: str,
    port: str,
    log_path: Path,
    *,
    power_confirmed: Callable[[], bool] | None = None,
    on_ready: Callable[[], None] | None = None,
    loopback_confirmed: bool = False,
    direct_connection_confirmed: bool = False,
    startup_complete: Callable[[], bool] | None = None,
    baudrate: int = 9600,
    timeout_seconds: float | None = None,
    raw_rx_path: Path | None = None,
    host_baud_confirmed: bool = False,
) -> dict[str, Any]:
    if mode not in ("listen-startup", "status", "loopback", "direct-test", "capture"):
        raise ValueError("Unknown diagnostic mode")
    if baudrate not in (9600, 19200, 38400):
        raise ValueError("RS-232 diagnostic baud must be 9600, 19200 or 38400")
    if baudrate != 9600 and (
        not host_baud_confirmed or mode not in ("status", "loopback", "capture")
    ):
        raise ValueError("Nondefault host baud requires a separately confirmed single-rate test")
    if timeout_seconds is not None and (
        mode not in ("status", "loopback", "capture")
        or not math.isfinite(timeout_seconds)
        or not 0.1 <= timeout_seconds <= 300
    ):
        raise ValueError("Capture/status/loopback timeout must be finite and in 0.1..300 seconds")
    if raw_rx_path is not None and raw_rx_path.resolve() == log_path.resolve():
        raise ValueError("Raw RX and JSONL log must use different paths")
    serial_config = {**SERIAL_CONFIG, "baudrate": baudrate}
    # An isolated adapter is required before even opening a loopback handle.
    if mode == "loopback" and not loopback_confirmed:
        raise ValueError(
            "Loopback requires explicit scanner-off/disconnected and Keyspan 2-3 confirmation"
        )
    if mode in ("listen-startup", "direct-test") and power_confirmed is None:
        raise ValueError("Startup capture requires an operator confirmation mechanism")
    if mode == "direct-test" and (not direct_connection_confirmed or startup_complete is None):
        raise ValueError("Direct test requires physical connection and startup confirmation gates")
    if crc16(STATUS_REQUEST[:-2]) != int.from_bytes(STATUS_REQUEST[-2:], "little"):
        raise ValueError("Golden status-request CRC does not match")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "serial_standard": "RS-232 intended; physical interface requires operator verification",
        "serial_config": serial_config,
        "host_baud_confirmed": host_baud_confirmed,
        "raw_rx_path": str(raw_rx_path.resolve()) if raw_rx_path is not None else None,
        "capture_completed": False,
        "dtr": False,
        "rts": False,
        "port_opened": False,
        "port_closed": True,
        "success": False,
        "tx_attempted_hex": "",
        "tx_bytes": 0,
        "tx_hex": "",
        "write_return": None,
        "flush_attempted": False,
        "flush_completed": None,
        "rx_bytes": 0,
        "rx_hex": "",
        "ack": False,
        "nak": False,
        "telegrams": [],
        "timeout_reason": None,
        "exception": None,
        "power_cycle_confirmed": False,
        "startup_received": False,
        "startup_complete_confirmed": False,
        "direct_connection_confirmed": direct_connection_confirmed,
        "loopback_passed": None,
        "physical_tx_verified": False,
        "tx_evidence_note": "write/flush report driver progress, not electrical pin measurement",
    }
    with ExitStack() as stack:
        raw_stream = None
        if raw_rx_path is not None:
            raw_rx_path.parent.mkdir(parents=True, exist_ok=True)
            # Refuse to replace evidence, before opening the serial device.
            raw_stream = stack.enter_context(raw_rx_path.open("xb"))
        stream = stack.enter_context(log_path.open("a", encoding="utf-8"))
        journal = Journal(stream, mode, port)
        capture = Capture(journal, report, raw_stream)
        device: serial.Serial | None = None
        receive_start: float | None = None
        try:
            journal.emit("opening", **report)
            device = serial.Serial(port=None, **serial_config)
            device.port, device.dtr, device.rts = port, False, False
            device.open()
            report["port_opened"], report["port_closed"] = True, False
            report["initial_state"] = initial_state(device)
            journal.emit("opened", **report["initial_state"])
            report["dcb_after_configuration"] = verify_windows_serial(
                device, baudrate, "after_configuration", journal.emit
            )
            # No explicit reset_input_buffer: Windows pyserial itself purges during open.
            # Startup therefore must begin after this ready event.
            receive_start = time.monotonic()
            if mode == "capture":
                seconds = 10.0 if timeout_seconds is None else timeout_seconds
                journal.emit("listener_ready", tx_bytes=0, timeout_seconds=seconds)
                if on_ready is not None:
                    on_ready()
                while time.monotonic() - receive_start < seconds:
                    capture.read(device, "passive")
                report["capture_completed"] = True
                # Completion of a passive capture is distinct from valid communication.
                report["success"] = capture.scanner_response_frames > 0
            if mode in ("listen-startup", "direct-test"):
                journal.emit(
                    "listener_ready",
                    tx_bytes=0,
                    ready_timeout_seconds=READY_SECONDS,
                    startup_timeout_seconds=STARTUP_SECONDS,
                    message="Passive listener ready; operator power-cycle confirmation required.",
                )
                if on_ready is not None:
                    on_ready()
                ready_deadline = receive_start + READY_SECONDS
                startup_deadline: float | None = None
                completion_deadline: float | None = None
                while True:
                    now = time.monotonic()
                    if (
                        startup_deadline is None
                        and power_confirmed is not None
                        and power_confirmed()
                    ):
                        report["power_cycle_confirmed"] = True
                        startup_deadline = now + STARTUP_SECONDS
                        completion_deadline = now + READY_SECONDS
                        journal.emit(
                            "power_restored_confirmation", startup_timeout_seconds=STARTUP_SECONDS
                        )
                    if mode == "direct-test" and startup_deadline is not None:
                        if (
                            not report["startup_complete_confirmed"]
                            and startup_complete is not None
                            and startup_complete()
                        ):
                            report["startup_complete_confirmed"] = True
                            journal.emit("startup_complete_confirmation")
                        # Keep the same handle through the entire startup window AND the
                        # operator's readiness confirmation, even if a frame arrives early.
                        if now >= startup_deadline and report["startup_complete_confirmed"]:
                            break
                        if completion_deadline is not None and now >= completion_deadline:
                            report["timeout_reason"] = (
                                "Operator startup-complete confirmation not received within "
                                "300 seconds; no status sent"
                            )
                            break
                    elif now >= (
                        startup_deadline if startup_deadline is not None else ready_deadline
                    ):
                        report["timeout_reason"] = (
                            "No valid startup telegram within 65 seconds of confirmation"
                            if startup_deadline is not None
                            else "Operator power-cycle confirmation not received within 300 seconds"
                        )
                        break
                    capture.read(device, "passive")
                    if mode == "listen-startup" and capture.startup is not None:
                        report["success"] = True
                        break
                if mode == "direct-test":
                    report["passive_result"] = {
                        "tx_bytes": 0,
                        "rx_bytes": len(capture.raw),
                        "rx_hex": capture.raw.hex(" ").upper(),
                        "ack": report["ack"],
                        "nak": report["nak"],
                        "startup": capture.startup,
                        "startup_received": capture.startup is not None,
                        "listen_seconds": round(time.monotonic() - receive_start, 6),
                        "timeout_reason": report["timeout_reason"],
                    }
                    journal.emit("passive_complete", **report["passive_result"])
            if mode in ("status", "loopback") or (
                mode == "direct-test"
                and report["startup_complete_confirmed"]
                and report["timeout_reason"] is None
            ):
                # Preserve a short pre-TX sample; do not mistake queued ACK/B1 for this request.
                before = time.monotonic() + 0.1
                while time.monotonic() < before:
                    capture.read(device, "pre_tx", framed=mode != "loopback")
                report["pre_tx_rx_bytes"] = len(capture.raw)
                capture.tx_boundary = len(capture.raw)
                request = LOOPBACK_PATTERN if mode == "loopback" else STATUS_REQUEST
                report["tx_attempted_hex"] = request.hex(" ").upper()
                report["dcb_pre_tx"] = verify_windows_serial(
                    device, baudrate, "immediately_before_write", journal.emit
                )
                journal.emit("tx_attempt", count=len(request), hex=report["tx_attempted_hex"])
                report["tx_bytes"] = None  # Unknown if the driver raises after a partial write.
                written = device.write(request)
                report.update(
                    write_return=written,
                    tx_bytes=written,
                    tx_hex=request[:written].hex(" ").upper(),
                )
                journal.emit("write_returned", count=written, hex=report["tx_hex"])
                if written != len(request):
                    raise OSError(f"Short write: expected {len(request)}, got {written}; no retry")
                report["flush_attempted"] = True
                journal.emit("flush_started")
                flush_output(device)
                report["flush_completed"] = True
                journal.emit("flush_completed", out_waiting=device.out_waiting)
                receive_start = time.monotonic()
                status_seconds = DIRECT_STATUS_SECONDS if mode == "direct-test" else STATUS_SECONDS
                if timeout_seconds is not None:
                    status_seconds = timeout_seconds
                deadline = receive_start + status_seconds
                journal.emit("listening", timeout_seconds=status_seconds)
                # One fixed post-flush window; repeated ACK/noise cannot extend it.
                while time.monotonic() < deadline:
                    capture.read(device, "post_tx", framed=mode != "loopback")
                    if mode == "status" and timeout_seconds is None and capture.post_nak:
                        report["timeout_reason"] = "NAK received; no retry"
                        break
                    if mode == "status" and timeout_seconds is None and capture.status is not None:
                        report["success"] = True
                        report["status_response"] = capture.status
                        break
                    if mode == "loopback":
                        echo = bytes(capture.raw[capture.tx_boundary :])
                        if not request.startswith(echo):
                            report["timeout_reason"] = (
                                "Loopback data differs from transmitted pattern"
                            )
                            break
                else:
                    if mode in ("status", "direct-test"):
                        report["success"] = capture.status is not None and not capture.post_nak
                        report["status_response"] = capture.status
                    if mode == "loopback":
                        report["loopback_passed"] = (
                            bytes(capture.raw[capture.tx_boundary :]) == request
                        )
                        report["success"] = report["loopback_passed"]
                    if not report["success"]:
                        report["timeout_reason"] = (
                            "No exact loopback echo"
                            if mode == "loopback"
                            else (
                                "NAK received; no retry"
                                if capture.post_nak
                                else f"No complete ACK + valid B1 within {status_seconds:g} "
                                "seconds after flush"
                            )
                        )
        except KeyboardInterrupt as exc:
            report["exception"] = exception_details(exc)
            report["timeout_reason"] = "Interrupted by operator; no additional telegram sent"
        except (OSError, ValueError, ProtocolError) as exc:
            report["exception"] = exception_details(exc)
        finally:
            if receive_start is not None:
                report["listen_seconds"] = round(time.monotonic() - receive_start, 6)
            if report["flush_attempted"] and report["flush_completed"] is None:
                report["flush_completed"] = False
            if mode == "loopback" and report["loopback_passed"] is None and report["port_opened"]:
                report["loopback_passed"] = False
            if device is not None:
                try:
                    device.close()
                except OSError as exc:
                    report["close_exception"] = exception_details(exc)
                report["port_closed"] = not device.is_open
            report.update(
                rx_bytes=len(capture.raw),
                rx_hex=capture.raw.hex(" ").upper(),
                startup_received=capture.startup is not None,
                startup=capture.startup,
                framing=asdict(capture.framer.stats),
                trailing_partial_hex=capture.framer.buffer.hex(" ").upper(),
                post_tx_ack=capture.post_ack,
                post_tx_nak=capture.post_nak,
            )
            if capture.tx_boundary is not None:
                report["post_tx_rx_bytes"] = len(capture.raw) - capture.tx_boundary
                report["post_tx_rx_hex"] = capture.raw[capture.tx_boundary :].hex(" ").upper()
            if not report["port_closed"]:
                report["success"] = False
            report["receive_evidence"] = {
                "any_bytes": bool(capture.raw),
                "crc_valid_telegrams": capture.framer.stats.frames,
                "scanner_response_frames": capture.scanner_response_frames,
                "crc_failed_candidates": capture.framer.stats.crc_errors,
                "invalid_lengths": capture.framer.stats.invalid_lengths,
                "unframed_bytes": capture.framer.stats.noise_bytes,
                "incomplete_suffix_bytes": len(capture.framer.buffer),
                "note": "ACK/NAK-shaped bytes alone, especially amid noise, do not prove a reply",
            }
            journal.emit("result", **report)
    return report


def run_status_repeat(
    port: str, log_path: Path, *, attempts: int = 10, confirmed: bool = False
) -> dict[str, Any]:
    """One native handle; bounded, paced status requests only on explicit operator request."""
    if not confirmed:
        raise ValueError("Repeated status requests require explicit operator confirmation")
    if not 1 <= attempts <= 10:
        raise ValueError("Status repetition must be bounded to 1..10 attempts")
    if crc16(STATUS_REQUEST[:-2]) != int.from_bytes(STATUS_REQUEST[-2:], "little"):
        raise ValueError("Golden status-request CRC does not match")
    report: dict[str, Any] = {
        "success": False,
        "port_opened": False,
        "port_closed": True,
        "serial_config": SERIAL_CONFIG,
        "status_request_hex": STATUS_REQUEST.hex(" ").upper(),
        "max_attempts": attempts,
        "attempts": [],
        "telegrams": [],
        "ack": False,
        "nak": False,
        "exception": None,
        "stop_reason": None,
        "physical_tx_verified": False,
        "post_flush_seconds_per_attempt": 5.0,
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("x", encoding="utf-8") as stream:
        journal = Journal(stream, "status-repeat", port)
        capture = Capture(journal, report)
        device: serial.Serial | None = None
        attempt: dict[str, Any] | None = None
        try:
            journal.emit("opening", **report)
            device = serial.Serial(port=None, **SERIAL_CONFIG)
            device.port, device.dtr, device.rts = port, False, False
            device.open()
            report.update(port_opened=True, port_closed=False)
            journal.emit("opened", **initial_state(device))
            report["dcb_after_configuration"] = verify_windows_serial(
                device, 9600, "after_configuration", journal.emit
            )
            # Record bytes available after open. Windows pyserial purges during open;
            # after that, never explicitly reset RX, flush input, or reopen.
            before = time.monotonic() + 0.1
            while time.monotonic() < before:
                capture.read(device, "pre_tx")
            for number in range(1, attempts + 1):
                capture.tx_boundary = len(capture.raw)
                capture.post_ack = capture.post_nak = False
                capture.status = None
                attempt = {
                    "number": number,
                    "tx_hex": STATUS_REQUEST.hex(" ").upper(),
                    "write_return": None,
                    "flush_completed": False,
                    "rx_start": len(capture.raw),
                }
                report["attempts"].append(attempt)
                attempt["dcb_pre_tx"] = verify_windows_serial(
                    device, 9600, "immediately_before_write", journal.emit
                )
                journal.emit("tx_attempt", attempt=number, count=7, hex=attempt["tx_hex"])
                written = device.write(STATUS_REQUEST)
                attempt["write_return"] = written
                journal.emit("write_returned", attempt=number, count=written)
                if written != 7:
                    raise OSError(f"Short write: expected 7, got {written}; stop repetition")
                journal.emit("flush_started", attempt=number)
                flush_output(device)
                attempt["flush_completed"] = True
                journal.emit("flush_completed", attempt=number, out_waiting=device.out_waiting)
                started = time.monotonic()
                journal.emit("listening", attempt=number, timeout_seconds=5.0)
                while time.monotonic() - started < 5.0:
                    capture.read(device, "post_tx")
                attempt.update(
                    listen_seconds=round(time.monotonic() - started, 6),
                    rx_bytes=len(capture.raw) - attempt["rx_start"],
                    rx_hex=capture.raw[attempt["rx_start"] :].hex(" ").upper(),
                    ack=capture.post_ack,
                    nak=capture.post_nak,
                    status=capture.status,
                )
                journal.emit("attempt_result", **attempt)
                report["success"] = capture.status is not None and not capture.post_nak
                valid_frame = any(
                    t["crc_valid"] and t["offset_start"] >= capture.tx_boundary
                    for t in report["telegrams"]
                )
                if report["success"] or capture.post_ack or capture.post_nak or valid_frame:
                    report["stop_reason"] = "Response observed; no further status request sent"
                    break
            else:
                report["stop_reason"] = "Requested bounded attempts exhausted; no response observed"
        except (OSError, ValueError, ProtocolError, KeyboardInterrupt) as exc:
            report["exception"] = exception_details(exc)
            report["stop_reason"] = "Error/interruption; repetition stopped"
        finally:
            if attempt is not None and "rx_hex" not in attempt:
                attempt.update(
                    rx_bytes=len(capture.raw) - attempt["rx_start"],
                    rx_hex=capture.raw[attempt["rx_start"] :].hex(" ").upper(),
                )
            if device is not None:
                try:
                    device.close()
                except OSError as exc:
                    report["close_exception"] = exception_details(exc)
                report["port_closed"] = not device.is_open
            counts = [a["write_return"] for a in report["attempts"]]
            report.update(
                tx_requests=len(counts),
                tx_bytes=None if any(n is None for n in counts) else sum(counts),
                rx_bytes=len(capture.raw),
                rx_hex=capture.raw.hex(" ").upper(),
                framing=asdict(capture.framer.stats),
                trailing_partial_hex=capture.framer.buffer.hex(" ").upper(),
            )
            if not report["port_closed"]:
                report["success"] = False
            journal.emit("result", **report)
    return report


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="lms200-hardware-diagnostic")
    commands = result.add_subparsers(dest="command", required=True)
    for name in (
        "ports",
        "listen-startup",
        "status",
        "loopback",
        "direct-test",
        "status-repeat",
        "capture",
    ):
        command = commands.add_parser(name)
        command.add_argument(
            "--log", type=Path, default=Path("docs/diagnostics/hardware-raw.jsonl")
        )
        if name != "ports":
            command.add_argument("--port", required=True)
        if name in ("status", "loopback", "capture"):
            command.add_argument("--baud", type=int, choices=(9600, 19200, 38400), default=9600)
            command.add_argument(
                "--timeout", type=float, help="Overall receive seconds, 0.1..300; not per read"
            )
            command.add_argument(
                "--raw-rx", type=Path, help="New raw binary RX file; never overwrite"
            )
            command.add_argument(
                "--confirm-host-baud-test",
                action="store_true",
                help="Explicit separate test at this host rate; no scanner baud command is sent",
            )
        if name in ("status", "capture"):
            command.add_argument(
                "--confirm-scanner-interface",
                action="store_true",
                help="Confirm verified RS-232 data cable, powered/ready scanner, no loopback link, "
                "and all other COM-port programs closed",
            )
        if name == "status-repeat":
            command.add_argument("--attempts", type=int, choices=range(1, 11), default=10)
            command.add_argument("--confirm-repeated-status", action="store_true")
        if name in ("listen-startup", "direct-test"):
            command.add_argument(
                "--power-on-file",
                type=Path,
                required=name == "direct-test",
                help="New file created only after the operator confirms power restored",
            )
        if name == "direct-test":
            command.add_argument("--startup-complete-file", type=Path, required=True)
            command.add_argument(
                "--confirm-direct-connection",
                action="store_true",
                help="Confirm scanner off, isolator removed, gray cable directly fitted normally, "
                "no jumpers and all other COM-port programs closed",
            )
        if name == "loopback":
            command.add_argument(
                "--confirm-isolated-loopback",
                action="store_true",
                help="Confirm scanner off/disconnected, Keyspan on USB only, pins 2-3 linked",
            )
    return result


def main() -> None:
    cli = parser()
    args = cli.parse_args()
    if args.command in ("status", "capture") and not args.confirm_scanner_interface:
        cli.error("Verify the current powered/ready RS-232 setup; use --confirm-scanner-interface")
    if getattr(args, "baud", 9600) != 9600 and not args.confirm_host_baud_test:
        cli.error("Nondefault host baud needs a separately authorized --confirm-host-baud-test")
    if getattr(args, "timeout", None) is not None and (
        not math.isfinite(args.timeout) or not 0.1 <= args.timeout <= 300
    ):
        cli.error("--timeout must be finite and in 0.1..300 seconds")
    if args.command == "status-repeat":
        if not args.confirm_repeated_status:
            cli.error("Repeated status requests require --confirm-repeated-status")

        def interrupt_repeat(*_: Any) -> None:
            raise KeyboardInterrupt

        previous_repeat = signal.signal(signal.SIGTERM, interrupt_repeat)
        try:
            outcome = run_status_repeat(
                args.port, args.log, attempts=args.attempts, confirmed=args.confirm_repeated_status
            )
        finally:
            signal.signal(signal.SIGTERM, previous_repeat)
        if not outcome["success"]:
            cli.exit(1)
        return
    if args.command == "ports":
        args.log.parent.mkdir(parents=True, exist_ok=True)
        with args.log.open("a", encoding="utf-8") as stream:
            entries = [
                {
                    "port": p.device,
                    "description": p.description,
                    "manufacturer": p.manufacturer,
                    "pnp_hwid": p.hwid,
                    "usb_vid": p.vid,
                    "usb_pid": p.pid,
                }
                for p in list_ports.comports()
            ]
            Journal(stream, "ports", None).emit(
                "ports",
                ports=entries,
                tx_bytes=0,
                tx_hex="",
                rx_bytes=0,
                rx_hex="",
                write_return=None,
                flush_completed=None,
                ack=False,
                nak=False,
                telegrams=[],
                timeout_reason=None,
                exception=None,
                serial_config=None,
                note="Enumeration only; no port opened. USB IDs may be on the parent device.",
            )
        return
    if args.command == "loopback" and not args.confirm_isolated_loopback:
        cli.error(
            "Before loopback: scanner powered off, Keyspan disconnected from scanner cable, "
            "USB only; explicitly confirm Keyspan DB9 pins 2-3 joined. "
            "Then use --confirm-isolated-loopback."
        )
    confirm: Callable[[], bool] | None = None
    ready: Callable[[], None] | None = None
    complete: Callable[[], bool] | None = None
    if args.command == "direct-test":
        if not args.confirm_direct_connection:
            cli.error("All six physical direct-connection conditions must be explicitly confirmed")
        if args.startup_complete_file.exists():
            cli.error("Startup-complete confirmation file must not already exist")
        if args.startup_complete_file.resolve() == args.power_on_file.resolve():
            cli.error("Power-on and startup-complete confirmations require distinct fresh files")
        complete = args.startup_complete_file.exists
    if args.command in ("listen-startup", "direct-test"):
        if args.power_on_file is not None:
            if args.power_on_file.exists():
                cli.error("Power-on confirmation file must not already exist; use a fresh path")
            confirm = args.power_on_file.exists
        else:
            if not sys.stdin.isatty():
                cli.error("Interactive startup capture needs a terminal or --power-on-file")
            restored = threading.Event()

            def prompt() -> None:
                try:
                    input(
                        "Listener ready. Power-cycle only the LMS200 supply when safe; "
                        "press Enter after power is restored. "
                    )
                    restored.set()
                except EOFError:
                    pass

            def start_prompt() -> None:
                threading.Thread(target=prompt, daemon=True).start()

            ready = start_prompt
            confirm = restored.is_set

    def interrupt(*_: Any) -> None:
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGTERM, interrupt)
    try:
        outcome = run_diagnostic(
            args.command,
            args.port,
            args.log,
            power_confirmed=confirm,
            on_ready=ready,
            loopback_confirmed=getattr(args, "confirm_isolated_loopback", False),
            direct_connection_confirmed=getattr(args, "confirm_direct_connection", False),
            startup_complete=complete,
            baudrate=getattr(args, "baud", 9600),
            timeout_seconds=getattr(args, "timeout", None),
            raw_rx_path=getattr(args, "raw_rx", None),
            host_baud_confirmed=getattr(args, "confirm_host_baud_test", False),
        )
    finally:
        signal.signal(signal.SIGTERM, previous)
    if not outcome["success"] and not (
        args.command == "capture"
        and outcome["capture_completed"]
        and outcome["port_closed"]
        and outcome["exception"] is None
    ):
        cli.exit(1)


if __name__ == "__main__":
    main()
