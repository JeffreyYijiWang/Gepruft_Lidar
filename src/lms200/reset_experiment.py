"""One opt-in software reset; default invocation is offline review only.

SICK 8007954/Q501/2006-08-01, section 7.3, pp38-39. A reset clears fault
memory. Operator consent is required; this is not the read-only diagnostic.
"""

import argparse
import json
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import serial

from .hardware_diagnostic import (
    SERIAL_CONFIG,
    Capture,
    Journal,
    exception_details,
    flush_output,
    initial_state,
)
from .protocol.crc import crc16

RESET_REQUEST = bytes.fromhex("02 00 01 00 10 34 12")  # TL Table 7-3, p38.
CAPTURE_SECONDS = 65.0  # TL p38: up to 60 s initialization, plus host margin.


def plan() -> dict[str, Any]:
    if crc16(RESET_REQUEST[:-2]) != int.from_bytes(RESET_REQUEST[-2:], "little"):
        raise ValueError("Published reset request CRC mismatch")
    return {
        "mode": "single-software-reset",
        "port": "COM7",
        "serial_config": SERIAL_CONFIG,
        "request_hex": RESET_REQUEST.hex(" ").upper(),
        "request_crc": "1234",
        "maximum_writes": 1,
        "capture_seconds_after_flush": CAPTURE_SECONDS,
        "effect": (
            "Restarts scanner and clears fault memory; fields and fatal-error history retained"
        ),
        "led_expectation": (
            "Startup LED sequence is an inference, not a guaranteed LED-test command"
        ),
    }


def run(log: Path, *, confirmed_reset: bool, confirmed_hardware: bool) -> dict[str, Any]:
    if not confirmed_reset or not confirmed_hardware:
        raise ValueError(
            "Explicit fault-memory-clear consent and current hardware confirmation required"
        )
    if os.name != "nt":
        raise RuntimeError("This experiment is native Windows only")
    report: dict[str, Any] = {
        **plan(),
        "write_count": None,
        "flush_completed": False,
        "ack": False,
        "nak": False,
        "telegrams": [],
        "port_closed": None,
        "error": None,
    }
    # Exclusive creation protects previous evidence and precedes opening COM7.
    with log.open("x", encoding="utf-8") as stream:
        journal = Journal(stream, "single-software-reset", "COM7")
        capture = Capture(journal, report)
        device = None
        journal.emit("authorized_plan", **plan())
        try:
            device = serial.Serial(port=None, **SERIAL_CONFIG)
            device.dtr = False
            device.rts = False
            device.port = "COM7"
            device.open()
            journal.emit("listener_open", **initial_state(device))
            until = time.monotonic() + 0.1
            while time.monotonic() < until:
                capture.read(device, "pre_tx")
            capture.tx_boundary = len(capture.raw)
            journal.emit("tx", count=7, hex=RESET_REQUEST.hex(" ").upper())
            report["write_count"] = device.write(RESET_REQUEST)
            journal.emit("write_returned", count=report["write_count"])
            if report["write_count"] != 7:
                raise OSError("Short reset write; do not retry")
            journal.emit("flush_started")
            flush_output(device)
            report["flush_completed"] = True
            journal.emit("flush_completed", out_waiting=device.out_waiting)
            started = time.monotonic()
            while time.monotonic() - started < CAPTURE_SECONDS:
                capture.read(device, "post_tx")
            report["post_flush_read_seconds"] = time.monotonic() - started
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
            report["rx_bytes"] = len(capture.raw)
            report["rx_hex"] = capture.raw.hex(" ").upper()
            report["framer_stats"] = asdict(capture.framer.stats)
            report["partial_hex"] = capture.framer.buffer.hex(" ").upper()
            report["post_tx_ack"] = capture.post_ack
            report["post_tx_nak"] = capture.post_nak
            boundary = capture.tx_boundary
            replies = [
                frame
                for frame in report["telegrams"]
                if boundary is not None
                and frame["offset_start"] >= boundary
                and frame["address_hex"] in ("80", "81")
                and frame["crc_valid"]
            ]
            report["reset_reply_valid"] = any(
                frame["command_hex"] == "91" and frame["payload_length"] == 2 for frame in replies
            )
            report["startup_reply_valid"] = any(
                frame["command_hex"] == "90" and "identity" in frame for frame in replies
            )
            report["exchange_observed"] = bool(
                capture.post_ack
                and not capture.post_nak
                and report["reset_reply_valid"]
                and report["startup_reply_valid"]
            )
            report["led_observation"] = (
                "Await explicit operator report; never inferred from serial data"
            )
            journal.emit("final", **report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-reset-clears-fault-memory", action="store_true")
    parser.add_argument("--confirm-powered-on-hardware-unchanged", action="store_true")
    parser.add_argument("--log", type=Path)
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({"offline_review_only": True, **plan()}, indent=2))
        return
    if args.log is None:
        parser.error("--log must name a fresh file in docs/diagnostics")
    result = run(
        args.log,
        confirmed_reset=args.confirm_reset_clears_fault_memory,
        confirmed_hardware=args.confirm_powered_on_hardware_unchanged,
    )
    raise SystemExit(0 if result["exchange_observed"] and not result["error"] else 1)


if __name__ == "__main__":
    main()
