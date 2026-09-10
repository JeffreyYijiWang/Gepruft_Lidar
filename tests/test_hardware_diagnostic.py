"""Synthetic serial streams, except explicitly cited published startup golden bytes."""

import json
import threading

import pytest

from lms200 import hardware_diagnostic as hd
from lms200.protocol.framing import FrameCandidate, Framer, encode
from lms200.transports.simulator import SimulatorTransport

# SICK Quick Manual C.2 p9, full example including independent published checksum.
STARTUP = bytes.fromhex(
    "02 81 17 00 90 4C 4D 53 32 30 30 3B 33 30 31 30 36 33 3B 56 30 32 2E 30 36 20 13 64 5A"
)


class FakeSerial:
    def __init__(self, chunks=(), passive=False, initial=()):
        self.chunks = list(chunks)
        self.initial = list(initial)
        self.passive = passive
        self.is_open = False
        self.writes = []
        self.flushed = False
        self.in_waiting = 0
        self.out_waiting = 0
        self.cts = self.dsr = self.ri = self.cd = False
        self.clock = 0.0
        self.write_result = None
        self.fail_open = False
        self.interrupt = False

    def open(self):
        if self.fail_open:
            raise PermissionError(13, "COM_TEST busy")
        self.is_open = True

    def get_settings(self):
        return hd.SERIAL_CONFIG.copy()

    def write(self, data):
        self.writes.append(data)
        return len(data) if self.write_result is None else self.write_result

    def flush(self):
        self.flushed = True

    def read(self, size):
        self.clock += 0.05
        if self.interrupt:
            raise KeyboardInterrupt
        if self.initial:
            return self.initial.pop(0)
        if self.passive or self.writes:
            return self.chunks.pop(0) if self.chunks else b""
        return b""

    def close(self):
        self.is_open = False


def install(monkeypatch, device):
    def factory(**kwargs):
        assert kwargs == {"port": None, **hd.SERIAL_CONFIG}
        return device

    monkeypatch.setattr(hd.serial, "Serial", factory)
    monkeypatch.setattr(hd, "verify_windows_serial", lambda *args: {"synthetic_test": True})
    monkeypatch.setattr(hd.time, "monotonic", lambda: device.clock)


def status_frame(address=0x81):
    return encode(b"\xb1" + SimulatorTransport().status_data() + b"\x10", address)


def test_passive_startup_fragmented_preserves_noise_and_never_writes(tmp_path, monkeypatch):
    device = FakeSerial([b"noise", STARTUP[:2], STARTUP[2:12], STARTUP[12:]], passive=True)
    install(monkeypatch, device)
    path = tmp_path / "raw.jsonl"
    path.write_text('{"prior_evidence":true}\n')
    ready = []
    result = hd.run_diagnostic(
        "listen-startup",
        "COM_TEST",
        path,
        power_confirmed=lambda: True,
        on_ready=lambda: ready.append(True),
    )
    assert ready == [True] and result["startup_received"] and result["success"]
    assert result["startup"]["crc_expected"] == result["startup"]["crc_received"] == "5A64"
    assert result["startup"]["offset_start"] == 5
    assert result["rx_hex"] == (b"noise" + STARTUP).hex(" ").upper()
    assert not device.writes and not device.flushed and result["port_closed"]
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert records[0] == {"prior_evidence": True}
    assert (
        bytes.fromhex(" ".join(r["hex"] for r in records if r.get("event") == "rx"))
        == b"noise" + STARTUP
    )


@pytest.mark.parametrize("confirmed,reason", [(False, "300 seconds"), (True, "65 seconds")])
def test_passive_confirmation_and_startup_timeouts(tmp_path, monkeypatch, confirmed, reason):
    device = FakeSerial(passive=True)
    install(monkeypatch, device)
    result = hd.run_diagnostic(
        "listen-startup", "COM_TEST", tmp_path / "raw.jsonl", power_confirmed=lambda: confirmed
    )
    assert reason in result["timeout_reason"]
    assert result["port_closed"] and not device.writes


def test_status_sends_once_flushes_then_reads_fragmented_response(tmp_path, monkeypatch):
    frame = status_frame()
    device = FakeSerial([b"\x06", frame[:3], frame[3:81], frame[81:]])
    install(monkeypatch, device)
    result = hd.run_diagnostic("status", "COM_TEST", tmp_path / "raw.jsonl")
    assert result["success"] and result["ack"] and not result["nak"]
    assert device.writes == [bytes.fromhex("02 00 01 00 31 15 12")]
    assert result["write_return"] == 7 and result["flush_completed"] and device.flushed
    assert result["status_response"]["crc_valid"] and result["port_closed"]
    assert not result["physical_tx_verified"]
    assert not device.rts and not device.dtr


@pytest.mark.parametrize("failed_stage", ["after_configuration", "immediately_before_write"])
def test_dcb_failure_closes_handle_without_transmitting(tmp_path, monkeypatch, failed_stage):
    device = FakeSerial()
    install(monkeypatch, device)
    stages = []

    def verify(device, baud, stage, emit):
        stages.append(stage)
        if stage == failed_stage:
            raise OSError("synthetic GetCommState failure or DCB mismatch")
        return {"synthetic_test": True}

    monkeypatch.setattr(hd, "verify_windows_serial", verify)
    result = hd.run_diagnostic("status", "COM_TEST", tmp_path / "blocked.jsonl")
    assert failed_stage in stages and result["exception"]
    assert result["port_closed"] and not device.writes and not result["success"]


def test_capture_writes_raw_binary_before_parser_and_retains_partial(tmp_path, monkeypatch):
    partial = STARTUP[:11]
    wire = b"\x00\xff\r\n" + partial
    device = FakeSerial([wire[:5], *([b""] * 12), wire[5:]], passive=True)
    install(monkeypatch, device)
    binary = tmp_path / "capture.rx.bin"
    original_feed = hd.Framer.feed

    def feed(framer, data):
        assert binary.read_bytes().endswith(data)  # Evidence is persisted before decoding.
        return original_feed(framer, data)

    monkeypatch.setattr(hd.Framer, "feed", feed)
    result = hd.run_diagnostic(
        "capture",
        "COM_TEST",
        tmp_path / "capture.jsonl",
        timeout_seconds=1.5,
        raw_rx_path=binary,
    )
    assert binary.read_bytes() == wire
    assert result["capture_completed"] and result["port_closed"]
    assert not result["success"] and not device.writes and not device.flushed
    assert result["trailing_partial_hex"] == partial.hex(" ").upper()
    assert result["listen_seconds"] >= 1.5


@pytest.mark.parametrize(
    "wire,success", [(b"", False), (hd.STATUS_REQUEST, False), (STARTUP, True)]
)
def test_capture_silence_does_not_imply_valid_communication(tmp_path, monkeypatch, wire, success):
    device = FakeSerial([wire], passive=True)
    install(monkeypatch, device)
    result = hd.run_diagnostic("capture", "COM_TEST", tmp_path / "rx.jsonl", timeout_seconds=0.2)
    assert result["capture_completed"] and result["success"] is success
    assert not device.writes and result["port_closed"]


@pytest.mark.parametrize("baud", [19200, 38400])
def test_host_baud_override_is_one_fixed_rate_and_one_binary_status(tmp_path, monkeypatch, baud):
    device = FakeSerial([b"\x06", status_frame()])
    install(monkeypatch, device)
    configs = []

    def factory(**kwargs):
        configs.append(kwargs)
        return device

    monkeypatch.setattr(hd.serial, "Serial", factory)
    result = hd.run_diagnostic(
        "status",
        "COM_TEST",
        tmp_path / "status.jsonl",
        baudrate=baud,
        host_baud_confirmed=True,
        timeout_seconds=0.8,
        raw_rx_path=tmp_path / "status.rx.bin",
    )
    assert result["success"] and result["listen_seconds"] >= 0.8
    assert configs == [{"port": None, **hd.SERIAL_CONFIG, "baudrate": baud}]
    assert result["serial_config"]["baudrate"] == baud and hd.SERIAL_CONFIG["baudrate"] == 9600
    assert device.writes == [hd.STATUS_REQUEST] and result["port_closed"]


@pytest.mark.parametrize(
    "options",
    [
        {"baudrate": 500000, "host_baud_confirmed": True},
        {"baudrate": 19200},
        {"timeout_seconds": float("nan")},
        {"timeout_seconds": float("inf")},
        {"timeout_seconds": 0},
        {"timeout_seconds": 301},
    ],
)
def test_bad_options_never_open_port(tmp_path, monkeypatch, options):
    def forbidden(**kwargs):
        pytest.fail("Invalid options must fail before serial construction")

    monkeypatch.setattr(hd.serial, "Serial", forbidden)
    with pytest.raises(ValueError):
        hd.run_diagnostic("status", "COM_TEST", tmp_path / "rx.jsonl", **options)


def test_binary_output_refuses_overwrite_and_log_alias_before_open(tmp_path, monkeypatch):
    def forbidden(**kwargs):
        pytest.fail("Existing evidence must fail before serial construction")

    monkeypatch.setattr(hd.serial, "Serial", forbidden)
    binary = tmp_path / "old.bin"
    binary.write_bytes(b"preserve me")
    with pytest.raises(FileExistsError):
        hd.run_diagnostic("capture", "COM_TEST", tmp_path / "rx.jsonl", raw_rx_path=binary)
    with pytest.raises(ValueError, match="different paths"):
        hd.run_diagnostic("capture", "COM_TEST", binary, raw_rx_path=binary)
    assert binary.read_bytes() == b"preserve me"


@pytest.mark.parametrize("chunks", [[hd.LOOPBACK_PATTERN], [hd.LOOPBACK_PATTERN, b"extra"]])
def test_binary_loopback_rejects_extra_data_and_keeps_full_capture(tmp_path, monkeypatch, chunks):
    device = FakeSerial(chunks)
    install(monkeypatch, device)
    path = tmp_path / "loopback.rx.bin"
    result = hd.run_diagnostic(
        "loopback",
        "COM_TEST",
        tmp_path / "loopback.jsonl",
        loopback_confirmed=True,
        raw_rx_path=path,
        timeout_seconds=0.5,
    )
    assert result["loopback_passed"] is (len(chunks) == 1)
    assert device.writes == [hd.LOOPBACK_PATTERN] and result["port_closed"]
    assert path.read_bytes() == b"".join(chunks)


@pytest.mark.parametrize("command", ["status", "capture"])
def test_new_cli_requires_current_scanner_checklist_before_open(monkeypatch, command):
    monkeypatch.setattr(hd.sys, "argv", ["diag", command, "--port", "COM_TEST"])
    monkeypatch.setattr(
        hd.serial, "Serial", lambda **kwargs: pytest.fail("No physical confirmation")
    )
    with pytest.raises(SystemExit) as error:
        hd.main()
    assert error.value.code == 2


@pytest.mark.parametrize("address", [0x80, 0x81])
@pytest.mark.parametrize("split", [1, 4, 80])
@pytest.mark.parametrize("repeated", [False, True])
def test_delayed_status_fragments_survive_idle_reads(
    tmp_path, monkeypatch, address, split, repeated
):
    # Synthetic B1, with a 600 ms delivery gap exceeding the former 250 ms expiry.
    frame = status_frame(address)
    device = FakeSerial([b"\x06", frame[:split], *([b""] * 12), frame[split:]])
    install(monkeypatch, device)
    path = tmp_path / "fragmented.jsonl"
    if repeated:
        result = hd.run_status_repeat("COM_TEST", path, attempts=1, confirmed=True)
        decoded = result["attempts"][0]["status"]
    else:
        result = hd.run_diagnostic("status", "COM_TEST", path)
        decoded = result["status_response"]
    assert result["success"] and result["port_closed"]
    assert device.writes == [hd.STATUS_REQUEST]
    assert result["rx_hex"] == (b"\x06" + frame).hex(" ").upper()
    assert decoded["address_hex"] == f"{address:02X}"
    assert decoded["crc_valid"] and decoded["length"] == decoded["payload_length"] + 6


def test_incomplete_reply_retained_through_whole_timeout(tmp_path, monkeypatch):
    partial = status_frame()[:20]
    device = FakeSerial([b"\x06", partial])
    install(monkeypatch, device)
    result = hd.run_diagnostic("status", "COM_TEST", tmp_path / "partial.jsonl")
    assert not result["success"] and result["port_closed"]
    assert result["listen_seconds"] >= hd.STATUS_SECONDS
    assert result["trailing_partial_hex"] == partial.hex(" ").upper()
    assert result["framing"]["truncated_frames"] == 0
    assert result["rx_hex"] == (b"\x06" + partial).hex(" ").upper()


@pytest.mark.parametrize(
    "case", ["silence", "nak", "bad_crc", "partial", "without_ack", "old_reply"]
)
def test_status_failure_preserves_all_bytes_and_does_not_retry(tmp_path, monkeypatch, case):
    frame = status_frame()
    wire = {
        "silence": b"",
        "nak": b"\x15",
        "bad_crc": b"\x06" + frame[:-1] + bytes([frame[-1] ^ 1]),
        "partial": b"\x06" + frame[:20],
        "without_ack": frame,
        "old_reply": b"\x06" + frame,
    }[case]
    device = FakeSerial(
        [] if case == "old_reply" else [wire], initial=[wire] if case == "old_reply" else []
    )
    install(monkeypatch, device)
    result = hd.run_diagnostic("status", "COM_TEST", tmp_path / "raw.jsonl")
    assert not result["success"] and result["port_closed"]
    assert device.writes == [hd.STATUS_REQUEST]
    assert result["rx_hex"] == wire.hex(" ").upper()
    if case == "bad_crc":
        bad = [t for t in result["telegrams"] if not t["crc_valid"]]
        assert bad and bad[0]["crc_expected"] != bad[0]["crc_received"]


def test_loopback_cannot_open_without_physical_confirmation(tmp_path, monkeypatch):
    def forbidden(**kwargs):
        pytest.fail("No serial handle may be constructed before confirmation")

    monkeypatch.setattr(hd.serial, "Serial", forbidden)
    with pytest.raises(ValueError, match="confirmation"):
        hd.run_diagnostic("loopback", "COM_TEST", tmp_path / "raw.jsonl")


@pytest.mark.parametrize(
    "echo,passed",
    [
        (hd.LOOPBACK_PATTERN, True),
        (b"wrong", False),
        (hd.LOOPBACK_PATTERN + b"extra", False),
        (b"", False),
    ],
)
def test_confirmed_loopback_exact_bytes(tmp_path, monkeypatch, echo, passed):
    device = FakeSerial([echo[:3], echo[3:]])
    install(monkeypatch, device)
    result = hd.run_diagnostic(
        "loopback", "COM_TEST", tmp_path / "raw.jsonl", loopback_confirmed=True
    )
    assert result["success"] is passed and result["loopback_passed"] is passed
    assert device.writes == [hd.LOOPBACK_PATTERN]
    assert result["port_closed"]


@pytest.mark.parametrize("fault", ["busy", "short", "interrupt"])
def test_os_failures_and_interrupt_close_handle(tmp_path, monkeypatch, fault):
    device = FakeSerial()
    device.fail_open = fault == "busy"
    device.interrupt = fault == "interrupt"
    if fault == "short":
        device.write_result = 3
    install(monkeypatch, device)
    result = hd.run_diagnostic("status", "COM_TEST", tmp_path / "raw.jsonl")
    assert result["exception"] and result["port_closed"] and not result["success"]
    assert len(device.writes) <= 1


def test_flush_watchdog_bounds_stuck_driver(monkeypatch):
    device = FakeSerial()
    device.is_open = True
    closed = threading.Event()

    def close():
        device.is_open = False
        closed.set()

    def flush():
        assert closed.wait(1)

    device.close, device.flush = close, flush
    monkeypatch.setattr(hd, "FLUSH_SECONDS", 0.01)
    with pytest.raises(TimeoutError, match="flush"):
        hd.flush_output(device)
    assert not device.is_open


def test_candidate_offsets_include_noise_and_crc_recovery():
    candidates: list[FrameCandidate] = []
    broken = STARTUP[:-1] + bytes([STARTUP[-1] ^ 1])
    framer = Framer(candidates.append)
    framer.feed(b"xyz" + broken + STARTUP)
    assert candidates[0].offset == 3 and not candidates[0].crc_valid
    assert candidates[-1].offset == 3 + len(STARTUP) and candidates[-1].crc_valid


@pytest.mark.parametrize("flag", ["--baud", "--allow-writes", "--target-baud", "--scan"])
def test_cli_has_no_configuration_options(flag):
    with pytest.raises(SystemExit):
        hd.parser().parse_args(["status", "--port", "COM_TEST", flag])


class DirectSerial(FakeSerial):
    """Synthetic startup and status phases; never constructs a real serial device."""

    def __init__(self, startup=STARTUP, reply=None):
        super().__init__([b"\x06" + status_frame() if reply is None else reply])
        self.startup_chunks = [startup[:3], startup[3:]]
        self.open_count = 0
        self.write_times = []

    def open(self):
        self.open_count += 1
        super().open()

    def read(self, size):
        if not self.writes:
            self.clock += 0.05
            return self.startup_chunks.pop(0) if self.startup_chunks else b""
        return super().read(size)

    def write(self, data):
        self.write_times.append(self.clock)
        return super().write(data)

    def reset_input_buffer(self):
        pytest.fail("Direct test must preserve RX across startup and status")


@pytest.mark.parametrize("completion_time", [20.0, 90.0])
def test_direct_waits_for_full_startup_and_operator_on_one_handle(
    tmp_path, monkeypatch, completion_time
):
    device = DirectSerial()
    install(monkeypatch, device)
    path = tmp_path / "direct.jsonl"
    result = hd.run_diagnostic(
        "direct-test",
        "COM_TEST",
        path,
        direct_connection_confirmed=True,
        power_confirmed=lambda: device.clock >= 1.0,
        startup_complete=lambda: device.clock >= completion_time,
    )
    assert result["success"] and result["startup_complete_confirmed"]
    assert result["passive_result"]["rx_hex"] == STARTUP.hex(" ").upper()
    assert result["passive_result"]["tx_bytes"] == 0
    assert device.open_count == 1 and result["port_closed"]
    assert device.writes == [hd.STATUS_REQUEST]
    assert device.write_times[0] >= max(66.0, completion_time)
    assert result["listen_seconds"] >= 5.0
    assert result["post_tx_ack"] and result["status_response"]["crc_valid"]
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert all(r["timestamp"] for r in records if r["event"] == "rx")


@pytest.mark.parametrize("power,complete", [(False, True), (True, False)])
def test_direct_never_writes_without_both_operator_confirmations(
    tmp_path, monkeypatch, power, complete
):
    device = DirectSerial()
    install(monkeypatch, device)
    result = hd.run_diagnostic(
        "direct-test",
        "COM_TEST",
        tmp_path / "direct.jsonl",
        direct_connection_confirmed=True,
        power_confirmed=lambda: power,
        startup_complete=lambda: complete,
    )
    assert not device.writes and result["port_closed"] and not result["success"]
    assert result["timeout_reason"]


@pytest.mark.parametrize("reply", [b"", b"\x15", b"\x06", status_frame()])
def test_direct_records_full_five_seconds_on_failure_without_retry(tmp_path, monkeypatch, reply):
    device = DirectSerial(startup=b"\x00\x39\x14\x31", reply=reply)
    install(monkeypatch, device)
    result = hd.run_diagnostic(
        "direct-test",
        "COM_TEST",
        tmp_path / "direct.jsonl",
        direct_connection_confirmed=True,
        power_confirmed=lambda: True,
        startup_complete=lambda: True,
    )
    assert device.writes == [hd.STATUS_REQUEST] and result["port_closed"]
    assert result["listen_seconds"] >= 5.0 and not result["success"]
    assert not result["passive_result"]["startup_received"]
    assert result["post_tx_rx_hex"] == reply.hex(" ").upper()


def test_direct_physical_guard_prevents_open(tmp_path, monkeypatch):
    def forbidden(**kwargs):
        pytest.fail("No port construction before all six physical confirmations")

    monkeypatch.setattr(hd.serial, "Serial", forbidden)
    with pytest.raises(ValueError, match="physical connection"):
        hd.run_diagnostic(
            "direct-test",
            "COM_TEST",
            tmp_path / "direct.jsonl",
            power_confirmed=lambda: True,
            startup_complete=lambda: True,
        )


class RepeatingSerial(FakeSerial):
    def __init__(self, chunks=(), initial=()):
        super().__init__(chunks=chunks, initial=initial)
        self.open_count = 0
        self.write_times = []

    def open(self):
        self.open_count += 1
        super().open()

    def write(self, data):
        self.write_times.append(self.clock)
        return super().write(data)

    def reset_input_buffer(self):
        pytest.fail("Polling must never explicitly clear RX")


def test_status_repeat_bounded_paced_same_handle(tmp_path, monkeypatch):
    device = RepeatingSerial()
    install(monkeypatch, device)
    report = hd.run_status_repeat("COM_TEST", tmp_path / "poll.jsonl", confirmed=True)
    assert device.writes == [hd.STATUS_REQUEST] * 10
    assert device.open_count == 1 and report["port_closed"]
    assert report["tx_bytes"] == 70 and report["rx_bytes"] == 0
    assert all(b - a >= 5 for a, b in zip(device.write_times, device.write_times[1:], strict=False))
    assert all(a["flush_completed"] and a["listen_seconds"] >= 5 for a in report["attempts"])
    assert not report["success"]


@pytest.mark.parametrize(
    "wire,success",
    [(b"\x06" + status_frame(), True), (b"\x15", False), (b"\x06", False), (status_frame(), False)],
)
def test_status_repeat_stops_after_response_and_full_read_window(
    tmp_path, monkeypatch, wire, success
):
    device = RepeatingSerial([wire[:1], wire[1:]])
    install(monkeypatch, device)
    report = hd.run_status_repeat("COM_TEST", tmp_path / "poll.jsonl", confirmed=True)
    assert report["success"] is success and report["port_closed"]
    assert len(device.writes) == 1
    assert report["rx_hex"] == wire.hex(" ").upper()
    assert report["attempts"][0]["listen_seconds"] >= 5


def test_status_repeat_preserves_stale_reply_but_does_not_accept_it(tmp_path, monkeypatch):
    stale = b"\x06" + status_frame()
    device = RepeatingSerial(initial=[stale])
    install(monkeypatch, device)
    report = hd.run_status_repeat("COM_TEST", tmp_path / "poll.jsonl", attempts=2, confirmed=True)
    assert len(device.writes) == 2 and report["rx_hex"] == stale.hex(" ").upper()
    assert not report["success"]
    assert all(not a["ack"] and a["status"] is None for a in report["attempts"])


@pytest.mark.parametrize("attempts,confirmed", [(10, False), (0, True), (11, True)])
def test_status_repeat_requires_consent_and_bound_before_open(
    tmp_path, monkeypatch, attempts, confirmed
):
    def forbidden(**kwargs):
        pytest.fail("No serial construction before guard validation")

    monkeypatch.setattr(hd.serial, "Serial", forbidden)
    with pytest.raises(ValueError):
        hd.run_status_repeat(
            "COM_TEST", tmp_path / "poll.jsonl", attempts=attempts, confirmed=confirmed
        )


def test_status_repeat_short_write_stops_and_preserves_previous_log(tmp_path, monkeypatch):
    device = RepeatingSerial()
    device.write_result = 3
    install(monkeypatch, device)
    path = tmp_path / "poll.jsonl"
    report = hd.run_status_repeat("COM_TEST", path, confirmed=True)
    assert len(device.writes) == 1 and report["port_closed"] and report["exception"]
    assert report["tx_bytes"] == 3
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        hd.run_status_repeat("COM_TEST", path, confirmed=True)
    assert path.read_bytes() == original and device.open_count == 1
