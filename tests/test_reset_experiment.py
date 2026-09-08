"""Offline guards and bounded-write checks; no real serial devices."""

import json
from unittest.mock import Mock

import pytest

from lms200 import reset_experiment as reset


def test_published_reset_crc():
    assert reset.plan()["request_crc"] == "1234"


@pytest.mark.skipif(reset.os.name != "nt", reason="Windows-only experiment")
@pytest.mark.parametrize("kind", ["valid", "bad_crc", "noise", "nak"])
def test_reset_reply_evidence(tmp_path, monkeypatch, kind):
    # TL p39 Table 7-7 reset reply, and QM p9 startup vector (different address profile).
    wire = bytes.fromhex(
        "06 02 80 02 00 91 10 79 30 "
        "02 81 17 00 90 4C 4D 53 32 30 30 3B 33 30 31 30 36 33 3B "
        "56 30 32 2E 30 36 20 13 64 5A"
    )
    if kind == "bad_crc":
        wire = wire[:-1] + b"\x00"  # Deliberately corrupted synthetic input.
    elif kind == "noise":
        wire = bytes.fromhex("C0 39 14 31 21 31 01")
    elif kind == "nak":
        wire = b"\x15"
    device = Mock(is_open=True, in_waiting=0, out_waiting=0)
    fragments = iter(bytes([value]) for value in wire)
    device.read.side_effect = lambda size: next(fragments, b"")
    device.write.return_value = 7
    device.close.side_effect = lambda: setattr(device, "is_open", False)
    monkeypatch.setattr(reset.serial, "Serial", Mock(return_value=device))
    monkeypatch.setattr(reset, "initial_state", lambda device: {})
    monkeypatch.setattr(reset, "flush_output", lambda device: None)
    ticks = iter(range(1000))
    monkeypatch.setattr(reset.time, "monotonic", lambda: next(ticks))
    result = reset.run(tmp_path / "raw.jsonl", confirmed_reset=True, confirmed_hardware=True)
    assert result["exchange_observed"] == (kind == "valid")
    assert result["rx_hex"] == wire.hex(" ").upper()
    device.write.assert_called_once()


@pytest.mark.parametrize("consent,hardware", [(False, False), (False, True), (True, False)])
def test_missing_confirmation_never_opens_serial(tmp_path, monkeypatch, consent, hardware):
    factory = Mock(side_effect=AssertionError("Must not open serial"))
    monkeypatch.setattr(reset.serial, "Serial", factory)
    with pytest.raises(ValueError):
        reset.run(tmp_path / "raw.jsonl", confirmed_reset=consent, confirmed_hardware=hardware)
    factory.assert_not_called()


@pytest.mark.skipif(reset.os.name != "nt", reason="Windows-only experiment")
@pytest.mark.parametrize("write_count", [7, 3])
def test_one_write_and_no_retry_even_without_reply(tmp_path, monkeypatch, write_count):
    device = Mock()
    device.is_open = True
    device.in_waiting = 0
    device.out_waiting = 0
    device.read.return_value = b""
    device.write.return_value = write_count
    device.close.side_effect = lambda: setattr(device, "is_open", False)
    monkeypatch.setattr(reset.serial, "Serial", Mock(return_value=device))
    monkeypatch.setattr(reset, "initial_state", lambda device: {"is_open": True})
    flush = Mock()
    monkeypatch.setattr(reset, "flush_output", flush)
    ticks = iter(range(1000))
    monkeypatch.setattr(reset.time, "monotonic", lambda: next(ticks))
    logfile = tmp_path / "raw.jsonl"
    result = reset.run(logfile, confirmed_reset=True, confirmed_hardware=True)
    device.write.assert_called_once_with(bytes.fromhex("02 00 01 00 10 34 12"))
    device.reset_input_buffer.assert_not_called()
    device.close.assert_called_once()
    assert result["port_closed"] and not result["exchange_observed"]
    assert result["rx_bytes"] == 0
    assert result["write_count"] == write_count
    if write_count == 7:
        flush.assert_called_once_with(device)
        assert result["post_flush_read_seconds"] >= 65
    else:
        flush.assert_not_called()
        assert result["error"]["type"] == "OSError"
    assert json.loads(logfile.read_text().splitlines()[-1])["event"] == "final"
    with pytest.raises(FileExistsError):
        reset.run(logfile, confirmed_reset=True, confirmed_hardware=True)
    device.write.assert_called_once()
