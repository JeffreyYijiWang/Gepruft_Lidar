"""Offline Windows-bridge command gate and launch guards; never opens hardware."""

import json
import queue
from pathlib import Path
from unittest.mock import Mock

import pytest

from lms200 import ros2_status_experiment as rs


@pytest.mark.parametrize("split", range(1, 7))
def test_accepts_one_fragmented_binary_status(split):
    gate = rs.SingleStatusGate()
    wire = bytes.fromhex("02 00 01 00 31 15 12")
    assert gate.accept(wire[:split], startup_authorized=True) is None
    assert gate.accept(wire[split:], startup_authorized=True) == wire
    with pytest.raises(ValueError):
        gate.accept(wire, startup_authorized=True)


@pytest.mark.parametrize(
    "wire",
    [
        b"02 00 01 00 31 15 12",
        bytes.fromhex("02 00 01 00 10 34 12"),
        bytes.fromhex("02 00 02 00 20 24 34 08"),
        rs.STATUS_REQUEST + b"\x00",
    ],
)
def test_never_forwards_config_reset_ascii_or_extra_bytes(wire):
    with pytest.raises(ValueError):
        rs.SingleStatusGate().accept(wire, startup_authorized=True)


def test_startup_gate_blocks_even_status():
    with pytest.raises(ValueError):
        rs.SingleStatusGate().accept(rs.STATUS_REQUEST, startup_authorized=False)


@pytest.mark.parametrize("already_powered_on", [False, True])
def test_no_physical_open_without_current_confirmation(tmp_path, monkeypatch, already_powered_on):
    factory = Mock(side_effect=AssertionError("No hardware open"))
    process = Mock(side_effect=AssertionError("No ROS2 launch"))
    monkeypatch.setattr(rs.serial, "Serial", factory)
    monkeypatch.setattr(rs.subprocess, "Popen", process)
    with pytest.raises(ValueError):
        rs.run(tmp_path, confirmed=False, already_powered_on=already_powered_on)
    factory.assert_not_called()
    process.assert_not_called()


def test_power_checklists_are_mutually_exclusive(tmp_path, monkeypatch):
    run = Mock(side_effect=AssertionError("No hardware run"))
    monkeypatch.setattr(rs, "run", run)
    monkeypatch.setattr(
        "sys.argv",
        [
            "ros2_status_experiment",
            "--run",
            "--log-dir",
            str(tmp_path),
            "--confirm-off-direct-checklist",
            "--confirm-powered-on-direct-checklist",
        ],
    )
    with pytest.raises(SystemExit) as error:
        rs.main()
    assert error.value.code == 2
    run.assert_not_called()


@pytest.mark.parametrize(
    ("checklist", "already_powered_on"),
    [
        ("--confirm-off-direct-checklist", False),
        ("--confirm-powered-on-direct-checklist", True),
    ],
)
def test_cli_preserves_explicit_power_mode(tmp_path, monkeypatch, checklist, already_powered_on):
    run = Mock(return_value={"success": True})
    monkeypatch.setattr(rs, "run", run)
    monkeypatch.setattr(
        "sys.argv",
        ["ros2_status_experiment", "--run", "--log-dir", str(tmp_path), checklist],
    )
    with pytest.raises(SystemExit) as error:
        rs.main()
    assert error.value.code == 0
    run.assert_called_once_with(tmp_path, confirmed=True, already_powered_on=already_powered_on)


@pytest.mark.parametrize(
    ("ros_reader_ready", "tx_trigger_seen"), [(False, True), (True, True), (True, False)]
)
@pytest.mark.parametrize("already_powered_on", [False, True])
def test_run_keeps_physical_power_modes_distinct_and_waits_for_both_readers(
    tmp_path, monkeypatch, ros_reader_ready, tx_trigger_seen, already_powered_on
):
    """Exercise the controller with synthetic relay/device IO, never real COM7 or WSL."""
    diagnostics = tmp_path / "docs/diagnostics"
    diagnostics.mkdir(parents=True)
    run_dir = diagnostics / "powered-on"
    events = queue.Queue()
    clock = [0.0]
    transmitted_at = []
    process = Mock()
    process.returncode = 3
    process.poll.side_effect = lambda: (
        3 if transmitted_at and clock[0] - transmitted_at[0] >= 6 else None
    )
    collector = Mock()
    collector.start.side_effect = lambda: events.put({"event": "relay_ready"})
    device = Mock()
    device.is_open = False
    device.in_waiting = 0
    device.out_waiting = 0
    device.open.side_effect = lambda: setattr(device, "is_open", True)
    device.close.side_effect = lambda: setattr(device, "is_open", False)
    queued_tx = False

    def read(_):
        nonlocal queued_tx
        clock[0] += 1
        if clock[0] == 3 and ros_reader_ready:
            (run_dir / "ros2.ready").touch()
        if clock[0] == 4 and ros_reader_ready:
            assert not (run_dir / "status.trigger").exists()
            if not already_powered_on:
                (run_dir / "power-on.confirmed").touch()
        if clock[0] == 6 and ros_reader_ready and not already_powered_on:
            (run_dir / "startup-complete.confirmed").touch()
        if (run_dir / "status.trigger").exists() and not queued_tx:
            events.put(
                {
                    "event": "node_tx",
                    "hex": rs.STATUS_REQUEST.hex(),
                    "controller_status_trigger_seen": tx_trigger_seen,
                }
            )
            queued_tx = True
        return b""

    def write(packet):
        assert packet == rs.STATUS_REQUEST
        assert device.is_open
        assert (run_dir / "listener.ready").exists()
        assert (run_dir / "ros2.ready").exists()
        assert (run_dir / "status.trigger").exists()
        transmitted_at.append(clock[0])
        return len(packet)

    device.read.side_effect = read
    device.write.side_effect = write
    monkeypatch.setattr(rs, "REPO", tmp_path)
    monkeypatch.setattr(rs, "verify_build", lambda: {"files": {}})
    monkeypatch.setattr(rs, "wsl_path", str)
    monkeypatch.setattr(rs, "initial_state", lambda _: {})
    monkeypatch.setattr(rs, "flush_output", lambda _: None)
    monkeypatch.setattr(rs.queue, "Queue", lambda: events)
    monkeypatch.setattr(rs.threading, "Thread", lambda **_: collector)
    monkeypatch.setattr(rs.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(rs.serial, "Serial", lambda **_: device)
    monkeypatch.setattr(rs.subprocess, "Popen", lambda *_, **__: process)
    marker_reads = []
    original_exists = Path.exists

    def exists(path):
        if path.name in ("power-on.confirmed", "startup-complete.confirmed"):
            marker_reads.append(path.name)
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", exists)
    report = rs.run(run_dir, confirmed=True, already_powered_on=already_powered_on)

    assert report["start_mode"] == (
        "already_powered_on" if already_powered_on else "passive_power_on"
    )
    assert report["confirmation_source"] == (
        "pre_run_powered_on_checklist" if already_powered_on else "operator_marker_files"
    )
    assert report["port_closed"]
    device.open.assert_called_once()
    device.close.assert_called_once()
    rows = [json.loads(line) for line in (run_dir / "windows-raw.jsonl").read_text().splitlines()]
    names = [row["event"] for row in rows]
    if already_powered_on:
        assert not marker_reads
        assert not (run_dir / "power-on.confirmed").exists()
        assert not (run_dir / "startup-complete.confirmed").exists()
        assert "operator_off_checklist_confirmed" not in names
        assert "operator_power_on_confirmed" not in names
        assert "status_authorized_after_startup" not in names
        assert report["power_on_confirmed"] and report["startup_complete_confirmed"]
    else:
        assert "operator_off_checklist_confirmed" in names
        assert "operator_powered_on_checklist_confirmed" not in names
        assert "status_authorized_for_already_powered_on_scanner" not in names
    if ros_reader_ready and tx_trigger_seen:
        device.write.assert_called_once_with(rs.STATUS_REQUEST)
        if already_powered_on:
            assert 3 <= transmitted_at[0] < 65
        else:
            assert transmitted_at[0] >= 69
            assert report["power_on_confirmed"] and report["startup_complete_confirmed"]
            authorization = next(
                row for row in rows if row["event"] == "status_authorized_after_startup"
            )
            assert authorization["seconds"] >= 65
        assert report["post_flush_read_seconds"] >= 5
        assert (
            names.index("both_listeners_ready")
            < names.index(
                "status_authorized_for_already_powered_on_scanner"
                if already_powered_on
                else "status_authorized_after_startup"
            )
            < names.index("tx_attempt")
        )
    else:
        device.write.assert_not_called()
        assert (run_dir / "status.trigger").exists() == ros_reader_ready
        assert report["error"] is not None
