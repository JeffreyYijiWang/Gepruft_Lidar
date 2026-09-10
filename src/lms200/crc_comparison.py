"""Opt-in 20 valid / 20 reversed-CRC status requests on one COM7 listener.

Electrical timing is never inferred from Windows write times. See
docs/CRC_COMPARISON_AND_WIRE_TIMING.md for the separate measurement procedure.
"""

import argparse
import json
import signal
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import serial

from . import address_discovery as ad
from .protocol.crc import crc16

TEST_A = "A_valid"
TEST_B = "B_reversed_crc"
ATTEMPTS = 20
MAX_SECONDS = 60.0


def packets() -> tuple[bytes, bytes]:
    ad.validate_crc()
    valid = ad.request(0)
    invalid = valid[:-2] + valid[-2:][::-1]
    if (
        valid != bytes.fromhex("02 00 01 00 31 15 12")
        or crc16(valid[:-2]) != 0x1215
        or invalid != bytes.fromhex("02 00 01 00 31 12 15")
        or crc16(invalid[:-2]) == int.from_bytes(invalid[-2:], "little")
    ):
        raise ValueError("Valid/reversed CRC fixtures failed validation; do not open serial")
    return valid, invalid


def plan() -> dict[str, Any]:
    valid, invalid = packets()
    return {
        "experiment": "valid_vs_reversed_crc",
        "destination": "00",
        "test_a_attempts": 20,
        "test_b_attempts_only_if_a_silent": 20,
        "valid_request": valid.hex(" ").upper(),
        "invalid_request": invalid.hex(" ").upper(),
        "crc_calculated_over_0200010031": "1215",
        "correct_wire_crc": "15 12",
        "deliberately_reversed_wire_crc": "12 15",
        "reversed_crc_numeric_value": "1512",
        "one_whole_binary_write_per_attempt": True,
        "stop_on_any_rx_byte": True,
        "min_attempt_spacing_ms": 100,
        "target_silent_window_ms": [200, 228],
        "nominal_bit_us": 1e6 / 9600,
        "nominal_character_ms": 10000 / 9600,
        "nominal_seven_character_ms": 70000 / 9600,
        "electrical_timing_measured": False,
    }


class ComparisonIO(ad.DiscoveryIO, Protocol):
    def send_crc(self, test: str, attempt: int) -> dict[str, Any] | None: ...


class CRCWindowsIO(ad.WindowsIO):
    def send_crc(self, test: str, attempt: int) -> dict[str, Any] | None:
        valid, invalid = packets()
        if test not in (TEST_A, TEST_B) or not 1 <= attempt <= ATTEMPTS:
            raise ValueError("Unknown CRC test or attempt outside 1..20")
        previous = [row for row in self.tx_records if row["test"] == test]
        if len(previous) + 1 != attempt:
            raise ValueError("CRC attempts must be sequential and cannot be replayed")
        baseline = [row for row in self.tx_records if row["test"] == TEST_A]
        if test == TEST_A and any(row["test"] == TEST_B for row in self.tx_records):
            raise ValueError("Cannot return to baseline after invalid CRC testing")
        if test == TEST_B and (
            len(baseline) != 20 or any(row.get("classification") != "SILENT" for row in baseline)
        ):
            raise ValueError("Invalid CRC requires twenty completed silent baseline attempts")
        packet = valid if test == TEST_A else invalid
        context = {
            "phase": test,
            "test": test,
            "address": 0,
            "address_hex": "00",
            "attempt": attempt,
            "crc_calculated": "1215",
            "crc_intentionally_invalid": test == TEST_B,
            "correct_wire_crc": "15 12",
            "supplied_wire_crc": packet[-2:].hex(" ").upper(),
        }
        self.emit("crc_fixture_verified", **context, prefix_hex=packet[:5].hex(" ").upper())
        return self._send_packet(packet, context)


def compare(io: ComparisonIO) -> dict[str, Any]:
    started = io.now()
    io.wait(ad.PRE_TX_SECONDS)
    attempts: list[dict[str, Any]] = []

    def received() -> dict[str, Any]:
        capture = ad.finish_capture(io, 0 if attempts else None)
        if attempts:
            attempts[-1].update(capture)
            io.emit("attempt_finished", **attempts[-1])
        return {
            "attempts": attempts,
            "capture": capture,
            "response_test": attempts[-1]["test"] if attempts else "pre_tx",
            "both_crc_tests_silent": False,
            "all_addresses_silent": False,
        }

    for test in (TEST_A, TEST_B):
        if io.snapshot().raw:
            return received()
        if test == TEST_B:
            if len(attempts) != 20 or any(r["classification"] != "SILENT" for r in attempts):
                raise ValueError("Baseline was not twenty silent completed requests")
        io.emit("phase_started", phase=test, max_attempts=20, **plan())
        for attempt in range(1, 21):
            if io.now() - started >= MAX_SECONDS:
                raise TimeoutError("CRC comparison reached its 60-second sequence deadline")
            if attempts:
                io.wait(max(0, attempts[-1]["tx_started"] + ad.MIN_TX_INTERVAL - io.now()))
            if io.snapshot().raw:
                return received()
            result = io.send_crc(test, attempt)
            if result is None:
                return received()
            attempts.append(result)
            deadline = max(
                result["drained_at"] + 0.2 + 0.007 * ((attempt - 1) % 5),
                result["tx_started"] + ad.MIN_TX_INTERVAL,
            )
            while io.now() < deadline and not io.snapshot().raw:
                io.wait(min(0.05, deadline - io.now()))
            if io.snapshot().raw:
                return received()
            result.update(
                classification="SILENT",
                classifications=["SILENT"],
                rx_bytes=0,
                listen_seconds=io.now() - result["drained_at"],
            )
            io.emit("attempt_finished", **result)
        io.emit("crc_phase_finished", test=test, attempts=20, classification="SILENT", rx_bytes=0)
    if io.snapshot().raw:
        return received()
    return {
        "attempts": attempts,
        "response_test": None,
        "both_crc_tests_silent": True,
        "all_addresses_silent": False,
    }


def summarize(report: dict[str, Any]) -> dict[str, Any]:
    records = report["attempts"]
    capture = report["capture"]
    clean = bool(
        not report["error"]
        and not report.get("listener_error")
        and report["port_closed"]
        and report.get("listener_stopped")
        and report["raw_integrity_confirmed"]
    )
    response_test = records[-1]["test"] if records and capture["rx_bytes"] else None
    tests = {}
    for test, packet in zip((TEST_A, TEST_B), packets(), strict=True):
        selected = [row for row in records if row["test"] == test]
        rx_bytes = capture["rx_bytes"] if response_test == test else 0
        outcome = (
            capture["classification"]
            if rx_bytes
            else "SILENT"
            if len(selected) == 20 and clean
            else "NOT_ATTEMPTED"
            if not selected
            else "INCOMPLETE"
        )
        tests[test] = {
            "request_hex": packet.hex(" ").upper(),
            "attempts": len(selected),
            "rx_bytes": rx_bytes,
            "outcome": outcome,
            "classifications": capture["classifications"] if rx_bytes else [outcome],
        }
    return {
        "tests": tests,
        "response_test": response_test or ("pre_tx" if capture["rx_bytes"] else None),
        "both_crc_tests_silent": bool(clean and not capture["rx_bytes"] and len(records) == 40),
        "clean_capture_and_close": clean,
        "electrical_measurement": {
            "measured": False,
            "on_wire_bytes": None,
            "min_inter_character_gap_us": None,
            "max_inter_character_gap_us": None,
            "request_at_lms_rx": None,
            "lms_tx_activity_within_60ms": None,
            "implicated_physical_segment": None,
            "reason": "No oscilloscope or protocol-analyzer capture supplied to this program",
        },
    }


def run(
    output: Path,
    *,
    confirmed_hardware: bool,
    confirmed_reversed_crc: bool,
    factory: Callable[..., Any] = serial.Serial,
) -> dict[str, Any]:
    if not confirmed_reversed_crc:
        raise ValueError("The deliberately invalid CRC experiment requires explicit opt-in")
    experiment_plan = plan()  # Validate both buffers before opening COM7.

    def sequence(io: ad.WindowsIO) -> dict[str, Any]:
        if not isinstance(io, CRCWindowsIO):
            raise TypeError("CRC sequence needs its guarded serial adapter")
        return compare(io)

    report = ad.run(
        output,
        confirmed=confirmed_hardware,
        factory=factory,
        sequence=sequence,
        io_factory=CRCWindowsIO,
        experiment_plan=experiment_plan,
    )
    report.update(plan=experiment_plan, **summarize(report))
    (output / "result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    with (output / "events.jsonl").open("a", encoding="utf-8") as stream:
        ad.Journal(stream).emit("crc_comparison_result", **summarize(report))
    print(json.dumps(summarize(report), indent=2), flush=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--confirm-powered-on-scanner-interface", action="store_true")
    parser.add_argument("--confirm-reversed-crc", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.run:
        print(json.dumps({"offline_only": True, "serial_opened": False, **plan()}, indent=2))
        return
    if (
        args.output is None
        or not args.confirm_powered_on_scanner_interface
        or not args.confirm_reversed_crc
    ):
        parser.error(
            "Live execution needs both explicit confirmation flags and a new output directory"
        )

    def interrupt(*_: Any) -> None:
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGTERM, interrupt)
    try:
        report = run(args.output.resolve(), confirmed_hardware=True, confirmed_reversed_crc=True)
    finally:
        signal.signal(signal.SIGTERM, previous)
    labels = report["tests"][TEST_B]["classifications"]
    nak_observed = labels == ["NAK"]
    baseline_status = report["response_test"] == TEST_A and any(
        "decoded_status" in f and f["response_address_matches"] for f in report["capture"]["frames"]
    )
    raise SystemExit(
        0 if report["clean_capture_and_close"] and (nak_observed or baseline_status) else 1
    )


if __name__ == "__main__":
    main()
