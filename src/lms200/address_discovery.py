"""Opt-in COM7 status-address discovery with a persistent raw receive worker.

No scanner settings are written. See docs/ADDRESS_DISCOVERY.md for timing,
operator scope, byte classification, and the limits of Windows observations.
"""

import argparse
import hashlib
import json
import os
import signal
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO, Protocol, TextIO

import serial

from .hardware_diagnostic import SERIAL_CONFIG, exception_details, flush_output
from .protocol.crc import crc16
from .protocol.framing import MAX_PAYLOAD, Frame, encode
from .protocol.responses import ProtocolError, decode_status, response
from .windows_serial_state import verify_windows_serial

UNIVERSAL_ATTEMPTS = 50
INDIVIDUAL_ATTEMPTS = 5
PRE_TX_SECONDS = 0.2
MIN_TX_INTERVAL = 0.1
RX_IDLE_SECONDS = 0.25  # 14 ms scanner gap plus Windows/USB scheduling allowance.
ACK_FOLLOW_SECONDS = 1.0
RESPONSE_LIMIT_SECONDS = 15.0
OVERALL_SECONDS = 240.0
DISCOVERY_CONFIG = SERIAL_CONFIG | {"timeout": 0.01}


def request(address: int) -> bytes:
    if not 0 <= address <= 0x7F:
        raise ValueError("Destination address must be 00..7F")
    return encode(b"\x31", address)


def validate_crc() -> None:
    # Published vector: SICK Quick Manual C.2 p9; algorithm TL section 9 p107.
    if crc16(bytes.fromhex("02 00 01 00 31")) != 0x1215:
        raise ValueError("CRC self-check failed before serial open")
    if request(0) != bytes.fromhex("02 00 01 00 31 15 12"):
        raise ValueError("Universal status request differs from published bytes")


def classify(raw: bytes, address: int | None) -> dict[str, Any]:
    """Analyze a saved prefix without deleting bytes or treating payload as ACK.

    Complete bad-CRC candidates remain OTHER. Their payload is not rescanned for
    apparently standalone ACK/NAK. A partial candidate is retained through gaps.
    """
    controls: list[dict[str, Any]] = []
    frames: list[dict[str, Any]] = []
    other: list[dict[str, Any]] = []
    offset = 0
    pending = b""
    while offset < len(raw):
        value = raw[offset]
        if value in (0x06, 0x15):
            controls.append({"name": "ACK" if value == 6 else "NAK", "offset": offset})
            offset += 1
        elif value != 2:
            other.append({"offset": offset, "hex": f"{value:02X}", "reason": "non-STX byte"})
            offset += 1
        else:
            pending = raw[offset:]
            if len(pending) < 4:
                break
            length = int.from_bytes(pending[2:4], "little")
            if not 1 <= length <= MAX_PAYLOAD:
                # An invalid header cannot establish control-byte boundaries.
                other.append(
                    {
                        "offset": offset,
                        "hex": pending.hex(" ").upper(),
                        "reason": "invalid length; remainder retained as OTHER",
                    }
                )
                pending = b""
                break
            if len(pending) < length + 6:
                break
            packet = pending[: length + 6]
            expected, received = crc16(packet[:-2]), int.from_bytes(packet[-2:], "little")
            item: dict[str, Any] = {
                "offset": offset,
                "hex": packet.hex(" ").upper(),
                "payload_length": length,
                "telegram_size": len(packet),
                "address_hex": f"{packet[1]:02X}",
                "command_hex": f"{packet[4]:02X}",
                "crc_expected": f"{expected:04X}",
                "crc_received": f"{received:04X}",
                "crc_valid": expected == received,
                "expected_response_address": None if address is None else f"{address + 0x80:02X}",
                "response_address_matches": None
                if address is None
                else packet[1] == address + 0x80,
                "b1": packet[4] == 0xB1,
                "preceded_by_ack": any(c["name"] == "ACK" for c in controls),
            }
            if expected == received:
                if item["b1"]:
                    try:
                        # Decode the actual frame; report strict requested-address matching above.
                        item["decoded_status"] = asdict(
                            decode_status(
                                response(Frame(packet[1], packet[4:-2], packet), packet[1] & 0x7F)
                            )
                        )
                    except ProtocolError as exc:
                        item["decode_error"] = str(exc)
                frames.append(item)
            else:
                other.append(item | {"reason": "CRC mismatch"})
            offset += len(packet)
            pending = b""
    labels = [name for name in ("ACK", "NAK") if any(c["name"] == name for c in controls)]
    if frames:
        labels.append("RESPONSE")
    if pending:
        labels.append("PARTIAL")
    if other:
        labels.append("OTHER")
    primary = next(
        (name for name in ("PARTIAL", "RESPONSE", "NAK", "ACK", "OTHER") if name in labels),
        "SILENT",
    )
    return {
        "classification": primary,
        "classifications": labels or ["SILENT"],
        "rx_bytes": len(raw),
        "rx_hex": raw.hex(" ").upper(),
        "controls": controls,
        "frames": frames,
        "other": other,
        "partial_hex": pending.hex(" ").upper(),
    }


@dataclass(frozen=True)
class Snapshot:
    raw: bytes
    first_rx: float | None
    last_rx: float | None


class DiscoveryIO(Protocol):
    def now(self) -> float: ...
    def snapshot(self) -> Snapshot: ...
    def wait(self, seconds: float) -> None: ...
    def send(self, address: int, attempt: int) -> dict[str, Any] | None: ...
    def emit(self, event: str, **values: Any) -> None: ...


def finish_capture(io: DiscoveryIO, address: int | None) -> dict[str, Any]:
    io.emit(
        "transmissions_stopped_on_rx", address_hex=None if address is None else f"{address:02X}"
    )
    while True:
        snapshot = io.snapshot()
        parsed = classify(snapshot.raw, address)
        if snapshot.first_rx is None or snapshot.last_rx is None:
            raise OSError("Receive notification without a saved byte")
        ack_wait = (
            "ACK" in parsed["classifications"]
            and not parsed["frames"]
            and not parsed["partial_hex"]
        )
        idle = ACK_FOLLOW_SECONDS if ack_wait else RX_IDLE_SECONDS
        deadline = min(snapshot.first_rx + RESPONSE_LIMIT_SECONDS, snapshot.last_rx + idle)
        if io.now() >= deadline:
            reason = (
                "response_capture_limit"
                if io.now() >= snapshot.first_rx + RESPONSE_LIMIT_SECONDS
                else "receive_idle"
            )
            io.emit("response_capture_finished", reason=reason, **parsed)
            return parsed | {"capture_end_reason": reason}
        io.wait(min(0.05, deadline - io.now()))


def discover(io: DiscoveryIO) -> dict[str, Any]:
    """Bounded scheduling policy, independently testable without Windows/hardware."""
    started = io.now()
    io.wait(PRE_TX_SECONDS)
    previous_tx: float | None = None
    attempts: list[dict[str, Any]] = []
    for address in range(128):
        if address == 0:
            io.emit("phase_started", phase="universal", max_attempts=50)
        elif address == 1:
            # Every early received byte returns below; this requires 50 actual silent writes.
            if io.snapshot().raw:
                capture = finish_capture(io, 0)
                attempts[-1].update(capture)
                return {
                    "attempts": attempts,
                    "responsive_address": 0,
                    "capture": capture,
                    "all_addresses_silent": False,
                }
            assert len(attempts) == 50
            io.emit(
                "phase_started", phase="individual", universal_attempts=50, universal_rx_bytes=0
            )
        limit = UNIVERSAL_ATTEMPTS if address == 0 else INDIVIDUAL_ATTEMPTS
        for attempt in range(1, limit + 1):
            if io.now() - started >= OVERALL_SECONDS:
                raise TimeoutError("Address discovery exceeded overall deadline")
            if previous_tx is not None:
                io.wait(max(0.0, previous_tx + MIN_TX_INTERVAL - io.now()))
            if io.snapshot().raw:
                previous_address = attempts[-1]["address"] if attempts else None
                capture = finish_capture(io, previous_address)
                if attempts:
                    attempts[-1].update(capture)
                return {
                    "attempts": attempts,
                    "responsive_address": previous_address,
                    "capture": capture,
                    "all_addresses_silent": False,
                }
            result = io.send(address, attempt)
            if result is None:  # Bytes arrived during DCB/logging immediately before write.
                previous_address = attempts[-1]["address"] if attempts else None
                capture = finish_capture(io, previous_address)
                if attempts:
                    attempts[-1].update(capture)
                return {
                    "attempts": attempts,
                    "responsive_address": previous_address,
                    "capture": capture,
                    "all_addresses_silent": False,
                }
            attempts.append(result)
            previous_tx = result["tx_started"]
            # Deterministic 200..228 ms windows avoid a single fixed mirror-phase interval.
            window = 0.2 + 0.007 * ((len(attempts) - 1) % 5)
            deadline = max(result["drained_at"] + window, previous_tx + MIN_TX_INTERVAL)
            while io.now() < deadline and not io.snapshot().raw:
                io.wait(min(0.05, deadline - io.now()))
            if io.snapshot().raw:
                capture = finish_capture(io, address)
                result.update(capture)
                io.emit("attempt_finished", **result)
                return {
                    "attempts": attempts,
                    "responsive_address": address,
                    "capture": capture,
                    "all_addresses_silent": False,
                }
            result.update(
                classification="SILENT",
                classifications=["SILENT"],
                rx_bytes=0,
                listen_seconds=io.now() - result["drained_at"],
            )
            io.emit("attempt_finished", **result)
        io.emit(
            "address_finished",
            address_hex=f"{address:02X}",
            attempts=limit,
            classification="SILENT",
            rx_bytes=0,
            total_attempts=len(attempts),
        )
    return {
        "attempts": attempts,
        "responsive_address": None,
        "capture": classify(b"", None),
        "all_addresses_silent": True,
    }


class Journal:
    def __init__(self, stream: TextIO) -> None:
        self.stream = stream
        self.lock = threading.Lock()

    def emit(self, event: str, **values: Any) -> None:
        with self.lock:
            row = {
                "timestamp_utc": datetime.now(UTC).isoformat(),
                "monotonic_seconds": time.perf_counter(),
                "clock": "time.perf_counter (Windows QueryPerformanceCounter)",
                "pid": os.getpid(),
                "port": "COM7",
                "event": event,
                **values,
            }
            line = json.dumps(row)
            self.stream.write(line + "\n")
            self.stream.flush()
            visible = event in {
                "listener_ready",
                "listener_heartbeat",
                "rx_raw",
                "phase_started",
                "error",
                "listener_stopped",
                "port_closed",
                "run_finished",
                "transmissions_stopped_on_rx",
                "response_capture_finished",
            }
            if event == "address_finished":
                visible = int(values["address_hex"], 16) % 16 == 0 or values["address_hex"] == "7F"
            if visible:
                print(line, flush=True)


class Receiver:
    """The only read caller, running before TX and throughout writes/drains/waits."""

    def __init__(self, device: serial.Serial, raw_file: BinaryIO, journal: Journal) -> None:
        self.device, self.raw_file, self.journal = device, raw_file, journal
        self.condition = threading.Condition()
        self.ready, self.stop, self.any_rx = threading.Event(), threading.Event(), threading.Event()
        self.raw = bytearray()
        self.first_rx: float | None = None
        self.last_rx: float | None = None
        self.last_read_completed = time.perf_counter()
        self.read_calls = self.os_bytes = self.saved_bytes = 0
        self.error: BaseException | None = None
        self.context: dict[str, Any] = {"phase": "pre_tx", "address": None, "attempt": None}
        self.thread = threading.Thread(target=self._read, name="COM7-raw-listener", daemon=True)

    def _read(self) -> None:
        heartbeat = time.perf_counter()
        try:
            while not self.stop.is_set():
                read_started = time.perf_counter()
                data = self.device.read(max(1, min(4096, self.device.in_waiting)))
                returned = time.perf_counter()
                if data:
                    self.any_rx.set()  # Block later writes even while disk logging is in progress.
                with self.condition:
                    self.read_calls += 1
                    self.last_read_completed = returned
                    if data:
                        self.os_bytes += len(data)
                        count = self.raw_file.write(data)
                        if count != len(data):
                            raise OSError("Short raw evidence file write")
                        self.raw_file.flush()
                        self.saved_bytes += count
                        self.journal.emit(
                            "rx_raw",
                            **self.context,
                            count=count,
                            offset=len(self.raw),
                            hex=data.hex(" ").upper(),
                            read_started=read_started,
                            read_returned=returned,
                        )
                        self.raw.extend(data)  # Exposed to parser only after persistence and log.
                        if self.first_rx is None:
                            self.first_rx = returned
                        self.last_rx = returned
                    if not self.ready.is_set():
                        self.journal.emit(
                            "listener_ready",
                            read_calls=self.read_calls,
                            handle_hex=hex(self.device._port_handle),  # type: ignore[attr-defined]
                            raw_file_open=True,
                            raw_before_parser=True,
                        )
                        self.ready.set()
                    if returned - heartbeat >= 10:
                        self.journal.emit(
                            "listener_heartbeat",
                            read_calls=self.read_calls,
                            rx_os_bytes=self.os_bytes,
                            rx_saved_bytes=self.saved_bytes,
                            serial_is_open=self.device.is_open,
                        )
                        heartbeat = returned
                    self.condition.notify_all()
        except BaseException as exc:
            with self.condition:
                self.error = exc
                self.condition.notify_all()

    def snapshot(self) -> Snapshot:
        with self.condition:
            if self.error is not None:
                raise OSError(f"Persistent receive worker failed: {self.error!r}") from self.error
            if not self.thread.is_alive() and not self.stop.is_set():
                raise OSError("Persistent receive worker exited")
            if time.perf_counter() - self.last_read_completed > 2:
                raise TimeoutError("Receive worker has not completed a read for two seconds")
            return Snapshot(bytes(self.raw), self.first_rx, self.last_rx)


class WindowsIO:
    def __init__(self, device: serial.Serial, receiver: Receiver, journal: Journal) -> None:
        self.device, self.receiver, self.journal = device, receiver, journal
        self.tx_records: list[dict[str, Any]] = []

    now = staticmethod(time.perf_counter)

    def emit(self, event: str, **values: Any) -> None:
        self.journal.emit(event, **values)

    def snapshot(self) -> Snapshot:
        return self.receiver.snapshot()

    def wait(self, seconds: float) -> None:
        if seconds > 0:
            with self.receiver.condition:
                if self.receiver.any_rx.is_set():
                    self.receiver.condition.wait(seconds)
                else:
                    self.receiver.condition.wait_for(
                        lambda: self.receiver.error is not None or self.receiver.any_rx.is_set(),
                        timeout=seconds,
                    )
        self.snapshot()

    def send(self, address: int, attempt: int) -> dict[str, Any] | None:
        context = {
            "phase": "universal" if address == 0 else "individual",
            "address": address,
            "address_hex": f"{address:02X}",
            "attempt": attempt,
        }
        return self._send_packet(request(address), context)

    def _send_packet(self, packet: bytes, context: dict[str, Any]) -> dict[str, Any] | None:
        """Shared one-write status path; CRC comparison supplies its explicit test buffer."""
        address = context["address"]
        if (
            not isinstance(packet, bytes)
            or len(packet) != 7
            or not 0 <= address <= 0x7F
            or packet[:5] != bytes((2, address, 1, 0, 0x31))
        ):
            raise ValueError("Only a complete seven-byte destination-addressed status is allowed")
        self.snapshot()
        if self.receiver.any_rx.is_set():
            return None
        with self.receiver.condition:
            self.receiver.context = context
        verify_windows_serial(
            self.device,
            9600,
            "immediately_before_write",
            lambda event, **values: self.emit(event, **context, **values),
        )
        self.emit("tx_intent", **context, count=7, hex=packet.hex(" ").upper())
        self.snapshot()
        if self.receiver.any_rx.is_set():
            self.emit("tx_cancelled_on_rx", **context)
            return None
        result: dict[str, Any] = {
            **context,
            "request_hex": packet.hex(" ").upper(),
            "crc_value": f"{int.from_bytes(packet[-2:], 'little'):04X}",
            "crc_bytes": packet[-2:].hex(" ").upper(),
            "classification": "ERROR",
            "write_return": None,
        }
        self.tx_records.append(result)
        result["tx_started"] = self.now()
        written = self.device.write(packet)  # Exactly one binary call for all seven bytes.
        result.update(write_return=written, write_completed=self.now())
        result["write_call_ms"] = (result["write_completed"] - result["tx_started"]) * 1000
        self.emit("write_returned", **result)
        if written != 7:
            raise OSError(f"Short serial write: {written}/7; no retry")
        result["flush_started"] = self.now()
        flush_output(self.device)  # Wait for TX; never reset/purge RX.
        result.update(drained_at=self.now(), out_waiting=self.device.out_waiting)
        result["drain_call_ms"] = (result["drained_at"] - result["flush_started"]) * 1000
        if result["out_waiting"] != 0:
            raise OSError("Output queue did not drain")
        self.emit("flush_completed", **result)
        self.snapshot()  # A failed reader prevents every subsequent send.
        return result


def run(
    output: Path,
    *,
    confirmed: bool,
    factory: Callable[..., Any] = serial.Serial,
    sequence: Callable[[WindowsIO], dict[str, Any]] | None = None,
    io_factory: Callable[[serial.Serial, Receiver, Journal], WindowsIO] | None = None,
    experiment_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not confirmed:
        raise ValueError(
            "Current powered/ready RS-232/no-link/exclusive-COM7 confirmation required"
        )
    if os.name != "nt":
        raise OSError("Run natively on Windows using the Keyspan COM7 driver")
    validate_crc()
    output.mkdir(parents=True, exist_ok=False)
    report: dict[str, Any] = {
        "port": "COM7",
        "port_opened": False,
        "port_closed": True,
        "error": None,
        "all_addresses_silent": False,
        "attempts": [],
    }
    device = receiver = io = None
    with (
        (output / "events.jsonl").open("x", encoding="utf-8") as events,
        (output / "rx.bin").open("xb") as raw,
    ):
        journal = Journal(events)
        journal.emit(
            "run_started",
            requested_config=DISCOVERY_CONFIG,
            confirmed_current_setup=True,
            rx_raw_path=str(output / "rx.bin"),
            **(
                experiment_plan
                or {
                    "experiment": "address_discovery",
                    "universal_attempts": 50,
                    "individual_attempts": 5,
                }
            ),
        )
        try:
            device = factory(port=None, **DISCOVERY_CONFIG)
            device.port, device.dtr, device.rts = "COM7", False, False
            device.open()
            report["port_opened"], report["port_closed"] = True, False
            report["dcb_after_configuration"] = verify_windows_serial(
                device, 9600, "after_configuration", journal.emit
            )
            receiver = Receiver(device, raw, journal)
            receiver.thread.start()
            if not receiver.ready.wait(2):
                raise OSError(f"Listener did not complete its first read: {receiver.error!r}")
            receiver.snapshot()
            io = (io_factory or WindowsIO)(device, receiver, journal)
            report.update((sequence or discover)(io))
            if report["all_addresses_silent"] and io.snapshot().raw:
                last_address = io.tx_records[-1]["address"]
                report["capture"] = finish_capture(io, last_address)
                report["all_addresses_silent"] = False
        except (Exception, KeyboardInterrupt) as exc:
            report["error"] = exception_details(exc)
            journal.emit("error", **report["error"])
        finally:
            if receiver is not None:
                receiver.stop.set()
                receiver.thread.join(timeout=2)
                if receiver.thread.is_alive() and device is not None:
                    try:
                        device.cancel_read()
                    except Exception as exc:
                        report["cancel_read_error"] = exception_details(exc)
                    receiver.thread.join(timeout=2)
                report["listener_stopped"] = not receiver.thread.is_alive()
                report["listener_error"] = (
                    None if receiver.error is None else exception_details(receiver.error)
                )
                report.update(
                    read_calls=receiver.read_calls,
                    rx_os_bytes=receiver.os_bytes,
                    rx_saved_bytes=receiver.saved_bytes,
                    rx_hex=receiver.raw.hex(" ").upper(),
                )
                journal.emit(
                    "listener_stopped",
                    stopped=report["listener_stopped"],
                    read_calls=receiver.read_calls,
                    rx_os_bytes=receiver.os_bytes,
                    rx_saved_bytes=receiver.saved_bytes,
                    error=report["listener_error"],
                )
            if device is not None:
                try:
                    device.close()
                except Exception as exc:
                    report["close_error"] = exception_details(exc)
                report["port_closed"] = not device.is_open
                journal.emit("port_closed", confirmed=report["port_closed"])
            if io is not None:
                report["attempts"] = io.tx_records
            raw.flush()
            saved = (output / "rx.bin").read_bytes()
            report["raw_file_bytes"] = len(saved)
            report["raw_sha256"] = hashlib.sha256(saved).hexdigest()
            report["raw_integrity_confirmed"] = (
                receiver is not None
                and len(saved) == receiver.os_bytes == receiver.saved_bytes
                and saved == bytes(receiver.raw)
            )
            last_address = report["attempts"][-1]["address"] if report["attempts"] else None
            report["capture"] = classify(saved, last_address)
            if saved and report["attempts"]:
                report["attempts"][-1].update(report["capture"])
                if receiver is not None and receiver.first_rx is not None:
                    report["attempts"][-1]["first_rx_app_delay_ms"] = (
                        receiver.first_rx - report["attempts"][-1]["tx_started"]
                    ) * 1000
            report["attempts_per_address"] = {
                f"{address:02X}": sum(row["address"] == address for row in report["attempts"])
                for address in range(128)
            }
            report["driver_accepted_tx_bytes"] = sum(
                row.get("write_return") or 0 for row in report["attempts"]
            )
            report["all_addresses_silent"] = bool(
                report["all_addresses_silent"]
                and not saved
                and not report["error"]
                and not report.get("listener_error")
                and report["port_closed"]
                and report.get("listener_stopped")
                and report["raw_integrity_confirmed"]
            )
            report["physical_tx_proven"] = False
            (output / "result.json").write_text(
                json.dumps(report, indent=2) + "\n", encoding="utf-8"
            )
            journal.emit(
                "run_finished",
                attempts=len(report["attempts"]),
                driver_accepted_tx_bytes=report["driver_accepted_tx_bytes"],
                rx_bytes=len(saved),
                raw_integrity_confirmed=report["raw_integrity_confirmed"],
                all_addresses_silent=report["all_addresses_silent"],
                port_closed=report["port_closed"],
                result=str(output / "result.json"),
            )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--confirm-powered-on-scanner-interface", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    validate_crc()
    if not args.run:
        print(
            json.dumps(
                {
                    "offline_only": True,
                    "serial_opened": False,
                    "crc_self_check": "1215",
                    "universal_attempts": 50,
                    "individual_attempts": 5,
                    "maximum_requests": 685,
                    "stop_on_any_byte": True,
                    "persistent_reader": True,
                    "required_live_flags": (
                        "--run --confirm-powered-on-scanner-interface --output NEW_DIRECTORY"
                    ),
                },
                indent=2,
            )
        )
        return
    if not args.confirm_powered_on_scanner_interface or args.output is None:
        parser.error(
            "Live discovery requires current scanner/interface confirmation "
            "and a new output directory"
        )

    def interrupt(*_: Any) -> None:
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGTERM, interrupt)
    try:
        result = run(args.output.resolve(), confirmed=True)
    finally:
        signal.signal(signal.SIGTERM, previous)
    # No reply is a completed diagnostic, not a successful scanner exchange.
    valid = any(
        "decoded_status" in frame and frame["response_address_matches"]
        for frame in result["capture"]["frames"]
    )
    complete = (
        not result["error"]
        and not result.get("listener_error")
        and result["port_closed"]
        and result.get("listener_stopped")
        and result["raw_integrity_confirmed"]
    )
    raise SystemExit(0 if valid and complete else 1)


if __name__ == "__main__":
    main()
