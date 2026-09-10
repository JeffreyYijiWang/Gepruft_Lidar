"""Synthetic CRC A/B tests; physical COM7 is never opened by these tests."""

import json

import pytest
from test_address_discovery import FakeIO, FakeSerial, status_frame, windows_only

from lms200 import address_discovery as ad
from lms200 import crc_comparison as cc


class FakeCRCIO(FakeIO):
    def send_crc(self, test, attempt):
        result = self.send(0, attempt)
        packet = cc.packets()[test == cc.TEST_B]
        result.update(test=test, phase=test, request_hex=packet.hex(" ").upper())
        return result


def test_only_two_crc_bytes_are_reversed_and_golden_crc_validates():
    valid, invalid = cc.packets()
    assert valid == bytes.fromhex("02 00 01 00 31 15 12")
    assert invalid == bytes.fromhex("02 00 01 00 31 12 15")
    assert valid[:5] == invalid[:5] and len(valid) == len(invalid) == 7
    assert valid[::-1] != invalid
    assert cc.crc16(valid[:-2]) == 0x1215
    assert int.from_bytes(invalid[-2:], "little") == 0x1512


def test_exactly_twenty_valid_then_twenty_invalid_with_one_destination():
    io = FakeCRCIO()
    result = cc.compare(io)
    valid, invalid = cc.packets()
    assert result["both_crc_tests_silent"]
    assert len(io.sent) == 40 and io.now() < cc.MAX_SECONDS
    assert [r["request_hex"] for r in io.sent] == [valid.hex(" ").upper()] * 20 + [
        invalid.hex(" ").upper()
    ] * 20
    assert [r["attempt"] for r in io.sent] == list(range(1, 21)) * 2
    assert all(r["address"] == 0 and r["classification"] == "SILENT" for r in io.sent)
    assert all(
        b["tx_started"] - a["tx_started"] >= 0.1 for a, b in zip(io.sent, io.sent[1:], strict=False)
    )


@pytest.mark.parametrize(
    "raw,label", [(b"\x06", "ACK"), (b"\x15", "NAK"), (b"\x02", "PARTIAL"), (b"\xff", "OTHER")]
)
def test_any_baseline_byte_blocks_test_b(raw, label):
    io = FakeCRCIO({3: [(0.02, raw)]})
    result = cc.compare(io)
    assert len(io.sent) == 3
    assert all(r["test"] == cc.TEST_A for r in io.sent)
    assert result["capture"]["classification"] == label
    assert result["response_test"] == cc.TEST_A


@pytest.mark.parametrize(
    "raw,label", [(b"\x15", "NAK"), (b"\x06", "ACK"), (b"\x02", "PARTIAL"), (b"\xf0", "OTHER")]
)
def test_invalid_crc_stops_on_any_byte_including_unexpected_ack(raw, label):
    io = FakeCRCIO({21: [(0.02, raw)]})
    result = cc.compare(io)
    assert len(io.sent) == 21 and result["response_test"] == cc.TEST_B
    assert result["capture"]["classification"] == label
    assert io.sent[-1]["request_hex"] == "02 00 01 00 31 12 15"


def test_unexpected_framed_reply_to_bad_crc_is_preserved():
    frame = status_frame(0x80)
    io = FakeCRCIO({21: [(0.02, frame[:4]), (0.15, frame[4:])]})
    result = cc.compare(io)
    assert len(io.sent) == 21 and result["capture"]["frames"][0]["b1"]
    assert result["capture"]["rx_hex"] == frame.hex(" ").upper()


def test_late_baseline_byte_does_not_start_invalid_phase():
    class LateIO(FakeCRCIO):
        def emit(self, event, **values):
            super().emit(event, **values)
            if event == "crc_phase_finished" and values["test"] == cc.TEST_A:
                self.raw.extend(b"\x06")
                self.first_rx = self.last_rx = self.clock

    io = LateIO()
    result = cc.compare(io)
    assert len(io.sent) == 20 and result["response_test"] == cc.TEST_A


def test_no_tx_on_crc_self_check_failure_or_missing_invalid_crc_consent(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="explicit opt-in"):
        cc.run(tmp_path / "no-open", confirmed_hardware=True, confirmed_reversed_crc=False)
    monkeypatch.setattr(cc, "crc16", lambda data: 0)
    with pytest.raises(ValueError, match="fixtures failed"):
        cc.run(tmp_path / "bad-fixture", confirmed_hardware=True, confirmed_reversed_crc=True)
    assert not list(tmp_path.iterdir())


def test_invalid_crc_sender_requires_twenty_silent_baselines():
    io = cc.CRCWindowsIO(None, None, None)
    with pytest.raises(ValueError, match="twenty completed silent"):
        io.send_crc(cc.TEST_B, 1)
    io.tx_records = [{"test": cc.TEST_A, "classification": "SILENT"} for _ in range(19)]
    with pytest.raises(ValueError, match="twenty completed silent"):
        io.send_crc(cc.TEST_B, 1)
    io.tx_records.append({"test": cc.TEST_A, "classification": "ACK"})
    with pytest.raises(ValueError, match="twenty completed silent"):
        io.send_crc(cc.TEST_B, 1)


@windows_only
def test_one_real_receive_worker_across_both_crc_phases(tmp_path, monkeypatch):
    class FakeCRCSerial(FakeSerial):
        def write(self, packet):
            assert self.read_calls > 0
            self.writes.append(packet)
            if packet[-2:] == bytes.fromhex("12 15"):
                self.deliver_while_writer_is_blocked(b"\x15")
            return len(packet)

        def flush(self):
            pass

    def verify(device, baud, stage, emit):
        result = {"confirmed": True, "synthetic_test": True, "stage": stage}
        emit("windows_dcb_readback", **result)
        return result

    monkeypatch.setattr(ad, "verify_windows_serial", verify)
    monkeypatch.setattr(ad, "discover", lambda io: pytest.fail("Address scan must not run"))
    device = FakeCRCSerial()
    directory = tmp_path / "threaded-crc"
    result = cc.run(
        directory, confirmed_hardware=True, confirmed_reversed_crc=True, factory=lambda **kw: device
    )
    assert result["tests"][cc.TEST_A]["attempts"] == 20
    assert result["tests"][cc.TEST_A]["outcome"] == "SILENT"
    assert result["tests"][cc.TEST_B]["attempts"] == 1
    assert result["tests"][cc.TEST_B]["outcome"] == "NAK"
    assert device.open_calls == device.close_calls == 1
    assert result["clean_capture_and_close"] and result["raw_integrity_confirmed"]
    assert (directory / "rx.bin").read_bytes() == b"\x15"
    rows = [json.loads(line) for line in (directory / "events.jsonl").read_text().splitlines()]
    assert sum(r["event"] == "listener_ready" for r in rows) == 1
    assert sum(r["event"] == "windows_dcb_readback" for r in rows) == 22
    assert all(r["address"] == 0 for r in result["attempts"])
    assert result["electrical_measurement"]["measured"] is False
    assert result["electrical_measurement"]["max_inter_character_gap_us"] is None


def test_whole_message_reversal_is_rejected_before_write():
    io = cc.CRCWindowsIO(None, None, None)
    with pytest.raises(ValueError, match="seven-byte"):
        io._send_packet(cc.packets()[0][::-1], {"address": 0})
