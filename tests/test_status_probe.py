"""Synthetic serial exchanges; no physical device is opened by these tests."""

import json
import signal

import pytest

from lms200.cli import parser
from lms200.protocol.framing import encode
from lms200.status_probe import probe_status
from lms200.transports.simulator import SimulatorTransport


class FakeSerial:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.is_open = False
        self.writes = []
        self.events = []
        self.in_waiting = 1
        self.interrupt = False

    def open(self):
        self.is_open = True
        self.events.append("open")

    def reset_input_buffer(self):
        self.events.append("clear")

    def write(self, data):
        self.events.append("write")
        self.writes.append(data)
        return len(data)

    def read(self, size):
        if self.interrupt:
            signal.raise_signal(signal.SIGINT)
        return self.chunks.pop(0) if self.chunks else b""

    def close(self):
        self.events.append("close")
        self.is_open = False


def install_fake(monkeypatch, device):
    def factory(**kwargs):
        assert kwargs == {
            "port": None,
            "baudrate": 9600,
            "bytesize": 8,
            "parity": "N",
            "stopbits": 1,
            "timeout": 0.02,
            "write_timeout": 0.25,
            "xonxoff": False,
            "rtscts": False,
            "dsrdtr": False,
        }
        return device

    monkeypatch.setattr("lms200.status_probe.serial.Serial", factory)
    ticks = iter(n / 100 for n in range(10000))
    monkeypatch.setattr("lms200.status_probe.time.monotonic", lambda: next(ticks))


def status_frame(address=0x81):
    return encode(b"\xb1" + SimulatorTransport().status_data() + b"\x10", address)


def test_single_status_and_complete_transcript(tmp_path, monkeypatch, golden):
    frame = status_frame()
    device = FakeSerial([b"\x06", frame[:3], frame[3:87], frame[87:]])
    install_fake(monkeypatch, device)
    path = tmp_path / "probe.jsonl"
    result = probe_status("COM_TEST", path)
    assert result["success"] and result["port_closed"] and not device.is_open
    assert device.writes == [golden["status"]]
    assert device.events == ["open", "clear", "write", "close"]
    assert device.dtr is False and device.rts is False
    assert result["tx_bytes"] == 7 and result["rx_bytes"] == len(frame) + 1
    reply = result["response"]
    assert reply["crc_expected_hex"] == reply["crc_received_hex"]
    assert reply["device_status"]["baud"] == 9600
    assert reply["exact_model"] is None
    events = [json.loads(line) for line in path.read_text().splitlines()]
    assert events[-1]["event"] == "result"
    assert bytes.fromhex("".join(e["hex"] for e in events if e["event"] == "rx")) == b"\x06" + frame
    assert "SICK_LMS" not in path.read_text()


@pytest.mark.parametrize(
    "case", ["silence", "nak", "missing_ack", "bad_crc", "wrong_address", "partial"]
)
def test_failure_never_retries_or_sends_cleanup_command(tmp_path, monkeypatch, golden, case):
    frame = status_frame()
    exchanges = {
        "silence": [],
        "nak": [b"\x15"],
        "missing_ack": [frame],
        "bad_crc": [b"\x06" + frame[:-1] + bytes((frame[-1] ^ 1,))],
        "wrong_address": [b"\x06" + status_frame(0x82)],
        "partial": [b"\x06" + frame[:-1]],
    }
    device = FakeSerial(exchanges[case])
    install_fake(monkeypatch, device)
    result = probe_status("COM_TEST", tmp_path / "probe.jsonl")
    assert not result["success"] and result["error"] and result["port_closed"]
    assert device.writes == [golden["status"]]
    if case == "bad_crc":
        assert result["framing"]["crc_errors"] > 0


def test_sigint_closes_without_another_transmission(tmp_path, monkeypatch, golden):
    device = FakeSerial([])
    device.interrupt = True
    install_fake(monkeypatch, device)
    result = probe_status("COM_TEST", tmp_path / "probe.jsonl")
    assert "Interrupted" in result["error"]
    assert not device.is_open and result["port_closed"]
    assert device.writes == [golden["status"]]


def test_delayed_usb_ack_is_captured_without_retransmission(tmp_path, monkeypatch, golden):
    device = FakeSerial([b""] * 60 + [b"\x06", status_frame()])
    install_fake(monkeypatch, device)
    result = probe_status("COM_TEST", tmp_path / "delayed.jsonl")
    assert result["success"] and result["response"]["crc_valid"]
    assert result["listen_seconds"] > 0.6
    assert device.writes == [golden["status"]]
    assert result["port_closed"] and not device.is_open


def test_silence_listens_three_seconds_then_closes(tmp_path, monkeypatch, golden):
    device = FakeSerial([])
    install_fake(monkeypatch, device)
    result = probe_status("COM_TEST", tmp_path / "silence.jsonl")
    assert 3.0 <= result["listen_seconds"] < 3.1
    assert not result["success"] and result["rx_bytes"] == 0
    assert device.writes == [golden["status"]]
    assert result["port_closed"] and not device.is_open


def test_busy_port_does_not_transmit(tmp_path, monkeypatch):
    device = FakeSerial([])
    install_fake(monkeypatch, device)

    def busy():
        raise OSError("Port is busy")

    monkeypatch.setattr(device, "open", busy)
    result = probe_status("COM_TEST", tmp_path / "probe.jsonl")
    assert not result["port_opened"] and result["port_closed"]
    assert result["tx_bytes"] == 0 and not device.writes


def test_existing_log_prevents_port_open(tmp_path, monkeypatch):
    device = FakeSerial([])
    install_fake(monkeypatch, device)
    path = tmp_path / "existing.jsonl"
    path.write_text("Keep previous evidence")
    with pytest.raises(FileExistsError):
        probe_status("COM_TEST", path)
    assert not device.events


@pytest.mark.parametrize(
    "option", ["--baud", "--target-baud", "--serial-standard", "--allow-writes"]
)
def test_status_cli_excludes_configuration_options(option):
    with pytest.raises(SystemExit):
        parser().parse_args(["probe-status", "--port", "COM_TEST", "--log", "test.jsonl", option])
