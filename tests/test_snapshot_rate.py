"""Fast simulator scans may share a clock tick, especially on Windows."""

import pytest

from lms200.config import Settings
from lms200.state_machine import Device
from lms200.transports.simulator import SimulatorTransport


@pytest.mark.parametrize("times,rate", [([], 0), ([10, 10], 0), ([9, 9.5, 10], 2)])
def test_snapshot_handles_identical_timestamps(monkeypatch, times, rate):
    device = Device(Settings(), SimulatorTransport())
    device._times.extend(times)
    monkeypatch.setattr("lms200.state_machine.time.monotonic", lambda: 10)
    assert device.snapshot()["received_scan_hz"] == rate
