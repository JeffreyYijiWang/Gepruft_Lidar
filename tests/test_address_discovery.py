"""Synthetic address/reader tests. No test opens a physical serial port."""

import json
import queue
import threading
import time

import pytest

from lms200 import address_discovery as ad
from lms200.protocol.framing import encode

windows_only = pytest.mark.skipif(ad.os.name != "nt", reason="Native Windows run wrapper")


def status_frame(address):
    # Synthetic supported B1 layout; not a captured scanner reply.
    data = bytearray(146)
    data[:7] = b"V02.10 "
    data[100:104] = bytes.fromhex("B4 00 32 00")
    data[109:111] = bytes.fromhex("67 80")
    return encode(b"\xb1" + data + b"\x10", address)


class FakeIO:
    def __init__(self, responses=None, initial=None):
        self.clock = 0.0
        self.raw = bytearray()
        self.first_rx = self.last_rx = None
        self.responses = responses or {}
        self.scheduled = list(initial or [])
        self.sent = []
        self.events = []

    def now(self):
        return self.clock

    def snapshot(self):
        return ad.Snapshot(bytes(self.raw), self.first_rx, self.last_rx)

    def wait(self, seconds):
        deadline = self.clock + seconds
        if self.scheduled and self.scheduled[0][0] <= deadline:
            self.clock, data = self.scheduled.pop(0)
            self.raw.extend(data)
            if self.first_rx is None:
                self.first_rx = self.clock
            self.last_rx = self.clock
        else:
            self.clock = deadline

    def send(self, address, attempt):
        assert not self.raw, "A second write was attempted after RX"
        packet = ad.request(address)
        row = {
            "address": address,
            "attempt": attempt,
            "tx_started": self.clock,
            "drained_at": self.clock + 0.008,
            "write_return": 7,
            "request_hex": packet.hex(" ").upper(),
        }
        self.sent.append(row)
        self.scheduled.extend(
            (self.clock + delay, data) for delay, data in self.responses.get(len(self.sent), [])
        )
        self.scheduled.sort()
        self.clock += 0.008
        return row

    def emit(self, event, **values):
        self.events.append({"event": event, **values})


def test_all_685_attempts_are_serialized_and_every_crc_recomputed():
    ad.validate_crc()
    io = FakeIO()
    result = ad.discover(io)
    assert result["all_addresses_silent"]
    assert len(io.sent) == 685
    assert [r["address"] for r in io.sent] == [0] * 50 + [
        a for a in range(1, 128) for _ in range(5)
    ]
    assert 10 <= io.sent[50]["tx_started"] - io.sent[0]["tx_started"] <= 15
    assert io.now() < ad.OVERALL_SECONDS
    assert all(
        b["tx_started"] - a["tx_started"] >= 0.1 for a, b in zip(io.sent, io.sent[1:], strict=False)
    )
    assert all(0.2 - 1e-9 <= r["listen_seconds"] <= 0.228 + 1e-9 for r in io.sent)
    assert all(r["classification"] == "SILENT" for r in io.sent)
    assert len({r["request_hex"] for r in io.sent}) == 128
    for address in range(128):
        packet = ad.request(address)
        # Independent literal translation of the manual's two-byte working register.
        crc, pair = 0, [0, 0]
        for value in packet[:-2]:
            pair[1], pair[0] = pair[0], value
            crc = ((crc & 0x7FFF) << 1) ^ (0x8005 if crc & 0x8000 else 0)
            crc ^= pair[0] | pair[1] << 8
        assert packet[:5] == bytes([2, address, 1, 0, 0x31])
        assert packet[-2:] == crc.to_bytes(2, "little")


@pytest.mark.parametrize(
    "data,label", [(b"\x06", "ACK"), (b"\x15", "NAK"), (b"\x02", "PARTIAL"), (b"\x99", "OTHER")]
)
def test_any_universal_byte_stops_all_further_requests(data, label):
    io = FakeIO({4: [(0.02, data)]})
    result = ad.discover(io)
    assert len(io.sent) == 4 and result["responsive_address"] == 0
    assert result["capture"]["classification"] == label
    assert not result["all_addresses_silent"]
    assert not any(e.get("phase") == "individual" for e in io.events)


def test_ack_followed_by_delayed_fragmented_b1_and_last_response_address():
    packet = status_frame(0xFF)
    io = FakeIO(
        {685: [(0.02, b"\x06"), (0.6, packet[:3]), (0.7, packet[3:70]), (0.88, packet[70:])]}
    )
    result = ad.discover(io)
    assert len(io.sent) == 685
    frame = result["capture"]["frames"][0]
    assert frame["crc_valid"] and frame["response_address_matches"] and frame["b1"]
    assert frame["preceded_by_ack"] and "decoded_status" in frame
    assert result["capture"]["classifications"] == ["ACK", "RESPONSE"]


def test_individual_response_stops_scan_at_first_byte():
    packet = status_frame(0x81)
    io = FakeIO({52: [(0.015, packet[:4]), (0.09, packet[4:])]})
    result = ad.discover(io)
    assert len(io.sent) == 52 and result["responsive_address"] == 1
    assert result["capture"]["frames"][0]["response_address_matches"]
    assert sum(r["address"] == 0 for r in io.sent) == 50


def test_pre_tx_bytes_are_saved_and_prevent_every_send():
    io = FakeIO(initial=[(0.01, b"\xf0\x39\x02")])
    result = ad.discover(io)
    assert io.sent == [] and result["responsive_address"] is None
    assert result["capture"]["rx_hex"] == "F0 39 02"
    assert result["capture"]["classifications"] == ["PARTIAL", "OTHER"]


def test_receive_gap_expires_only_partial_capture_and_never_retries():
    io = FakeIO({1: [(0.02, b"\x02\x80\x05\x00\xb1"), (0.5, b"late")]})
    result = ad.discover(io)
    assert len(io.sent) == 1
    assert result["capture"]["classification"] == "PARTIAL"
    assert result["capture"]["partial_hex"] == "02 80 05 00 B1"


def test_complete_crc_bad_payload_controls_are_not_standalone_ack():
    bad = bytearray(encode(b"\xb1\x06\x15\x10", 0x80))
    bad[-1] ^= 1
    parsed = ad.classify(bytes(bad), 0)
    assert parsed["classification"] == "OTHER" and parsed["controls"] == []
    assert parsed["other"][0]["crc_valid"] is False


def test_length_is_little_endian_and_mismatched_address_is_reported():
    packet = encode(b"\xb1" + bytes(298) + b"\x10", 0xA0)
    partial = ad.classify(packet[:100], 1)
    assert partial["classification"] == "PARTIAL"
    parsed = ad.classify(b"\x06" + packet, 1)
    assert parsed["frames"][0]["telegram_size"] == 306
    assert parsed["frames"][0]["response_address_matches"] is False
    assert parsed["controls"] == [{"name": "ACK", "offset": 0}]


@windows_only
def test_request_validation_before_open(monkeypatch, tmp_path):
    monkeypatch.setattr(ad, "crc16", lambda data: 0)
    with pytest.raises(ValueError, match="CRC self-check"):
        ad.run(tmp_path / "no-open", confirmed=True, factory=lambda **kw: pytest.fail("Opened"))
    assert not (tmp_path / "no-open").exists()


class FakeSerial:
    def __init__(self, **kwargs):
        self.is_open = False
        self._port_handle = 12345
        self.incoming = queue.Queue()
        self.read_calls = self.open_calls = self.close_calls = 0
        self.writes = []
        self.consumed = threading.Event()
        self.closed = False
        self.fail_read = False
        self.short_write = False
        self.out_waiting = 0

    def open(self):
        self.open_calls += 1
        self.is_open = True

    @property
    def in_waiting(self):
        return 0

    def read(self, count):
        self.read_calls += 1
        if self.fail_read:
            raise OSError(5, "synthetic read failure")
        try:
            data = self.incoming.get(timeout=0.01)
            self.consumed.set()
            return data
        except queue.Empty:
            return b""

    def deliver_while_writer_is_blocked(self, data):
        self.consumed.clear()
        self.incoming.put(data)
        assert self.consumed.wait(0.5), "Receive thread must run concurrently with write/flush"
        time.sleep(0.02)

    def write(self, packet):
        assert self.read_calls > 0, "Listener must start before TX"
        self.writes.append(packet)
        if self.short_write:
            return 3
        self.deliver_while_writer_is_blocked(b"\x06")
        return len(packet)

    def flush(self):
        self.deliver_while_writer_is_blocked(status_frame(0x80))

    def close(self):
        self.close_calls += 1
        self.is_open = False

    def reset_input_buffer(self):
        pytest.fail("RX must never be reset after open")


@pytest.fixture
def synthetic_windows(monkeypatch):
    def verify(device, baud, stage, emit):
        result = {"confirmed": True, "synthetic_test": True, "stage": stage}
        emit("windows_dcb_readback", **result)
        return result

    monkeypatch.setattr(ad, "verify_windows_serial", verify)


@windows_only
def test_real_worker_records_bytes_during_write_and_flush(tmp_path, synthetic_windows):
    device = FakeSerial()
    output = tmp_path / "threaded"
    result = ad.run(output, confirmed=True, factory=lambda **kw: device)
    expected = b"\x06" + status_frame(0x80)
    assert (output / "rx.bin").read_bytes() == expected
    assert result["raw_integrity_confirmed"] and result["raw_file_bytes"] == len(expected)
    assert result["listener_stopped"] and result["port_closed"]
    assert result["listener_error"] is None and result["error"] is None
    assert device.open_calls == device.close_calls == 1
    assert len(device.writes) == 1 and len(result["attempts"]) == 1
    rows = [json.loads(line) for line in (output / "events.jsonl").read_text().splitlines()]
    events = [r["event"] for r in rows]
    assert events.index("listener_ready") < events.index("tx_intent")
    assert events.index("rx_raw") < events.index("write_returned")
    assert events.index("rx_raw") < events.index("response_capture_finished")
    assert b"".join(bytes.fromhex(r["hex"]) for r in rows if r["event"] == "rx_raw") == expected


@windows_only
def test_prewrite_dcb_failure_never_writes_and_closes(tmp_path, monkeypatch):
    device = FakeSerial()

    def verify(device, baud, stage, emit):
        if stage == "immediately_before_write":
            raise OSError("synthetic DCB mismatch")
        return {"confirmed": True, "synthetic_test": True}

    monkeypatch.setattr(ad, "verify_windows_serial", verify)
    result = ad.run(tmp_path / "dcb-failure", confirmed=True, factory=lambda **kw: device)
    assert device.writes == [] and result["port_closed"] and result["listener_stopped"]
    assert "DCB mismatch" in result["error"]["message"]
    assert not result["all_addresses_silent"]


@windows_only
def test_short_write_stops_without_retry(tmp_path, synthetic_windows):
    device = FakeSerial()
    device.short_write = True
    result = ad.run(tmp_path / "short", confirmed=True, factory=lambda **kw: device)
    assert len(device.writes) == 1 and result["driver_accepted_tx_bytes"] == 3
    assert result["port_closed"] and result["listener_stopped"]
    assert not result["all_addresses_silent"] and result["error"] is not None


@windows_only
def test_receive_failure_is_not_reported_as_silence(tmp_path, synthetic_windows):
    device = FakeSerial()
    device.fail_read = True
    result = ad.run(tmp_path / "read-failure", confirmed=True, factory=lambda **kw: device)
    assert device.writes == [] and result["port_closed"]
    assert result["listener_error"] is not None and not result["all_addresses_silent"]


@windows_only
def test_receive_during_prewrite_dcb_cancels_write(tmp_path, monkeypatch):
    device = FakeSerial()

    def verify(device, baud, stage, emit):
        if stage == "immediately_before_write":
            device.deliver_while_writer_is_blocked(b"\x99")
        return {"confirmed": True, "synthetic_test": True}

    monkeypatch.setattr(ad, "verify_windows_serial", verify)
    result = ad.run(tmp_path / "dcb-rx", confirmed=True, factory=lambda **kw: device)
    assert device.writes == [] and result["attempts"] == []
    assert result["capture"]["rx_hex"] == "99" and result["raw_integrity_confirmed"]
    assert result["port_closed"] and result["error"] is None


def test_late_universal_byte_blocks_phase_two():
    class LateIO(FakeIO):
        def emit(self, event, **values):
            super().emit(event, **values)
            if event == "address_finished" and values["address_hex"] == "00":
                self.raw.extend(b"\x06")
                self.first_rx = self.last_rx = self.clock

    io = LateIO()
    result = ad.discover(io)
    assert len(io.sent) == 50 and not result["all_addresses_silent"]
    assert result["capture"]["classification"] == "ACK"
    assert not any(e.get("phase") == "individual" for e in io.events)


def test_continuous_unclassified_input_is_bounded():
    io = FakeIO({1: [(0.1 * n, b"\x99") for n in range(1, 180)]})
    result = ad.discover(io)
    assert len(io.sent) == 1 and io.now() < 16
    assert result["capture"]["capture_end_reason"] == "response_capture_limit"


@windows_only
def test_interruption_closes_listener_and_preserves_report(
    tmp_path, synthetic_windows, monkeypatch
):
    device = FakeSerial()

    def interrupt(io):
        raise KeyboardInterrupt

    monkeypatch.setattr(ad, "discover", interrupt)
    result = ad.run(tmp_path / "interrupt", confirmed=True, factory=lambda **kw: device)
    assert device.writes == [] and result["listener_stopped"] and result["port_closed"]
    assert result["error"]["type"] == "KeyboardInterrupt"
    assert (tmp_path / "interrupt/result.json").exists()
