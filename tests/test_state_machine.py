import asyncio
from dataclasses import replace

import pytest

from lms200.config import Settings
from lms200.protocol.commands import status_request
from lms200.protocol.responses import ProtocolError
from lms200.state_machine import Device, State
from lms200.transports.simulator import SimulatorTransport


async def wait_scan(device):
    async with asyncio.timeout(2):
        while device.latest is None:
            await asyncio.sleep(0.01)


async def test_complete_sequence_and_shutdown():
    sim = SimulatorTransport(realtime=False)
    device = Device(Settings(target_baud=38400), sim)
    try:
        await device.initialize()
        await wait_scan(device)
        assert device.state == State.STREAMING
        assert device.latest.count == 181
        assert sim.device_baud == sim.baud == 38400
        commands = sim.commands
        assert commands[0] == b"\x31"
        assert commands.index(b"\x20\x00SICK_LMS") < commands.index(b"\x20\x40")
        assert commands.index(b"\x20\x40") < next(i for i, c in enumerate(commands) if c[0] == 0x77)
        assert commands[-1] == b"\x20\x24"
        assert State.VERIFYING in device.history
    finally:
        await device.close()
    assert sim.commands[-1] == b"\x20\x25"
    assert device.state == State.DISCONNECTED and sim.mode == 0x25


async def test_readonly_probe_does_not_configure_or_stop():
    sim = SimulatorTransport(realtime=False)
    device = Device(Settings(transport="serial", serial_port="mock", read_only=True), sim)
    await device.connect()
    await device.close()
    assert [c[0] for c in sim.commands] == [0x31, 0x3A, 0x74]


async def test_hardware_consent_required_before_opening():
    sim = SimulatorTransport()
    device = Device(Settings(transport="serial", serial_port="mock", read_only=False), sim)
    with pytest.raises(ValueError, match="Confirm"):
        await device.initialize()
    assert sim._producer is None and not sim.commands


async def test_no_redundant_eprom_write():
    sim = SimulatorTransport(realtime=False)
    sim.resolution = 1
    sim.config = sim.config.updated("mm")
    device = Device(Settings(), sim)
    await device.initialize()
    await device.close()
    assert not any(c[0] in (0x77, 0x3B) for c in sim.commands)
    assert b"\x20\x00SICK_LMS" not in sim.commands


async def test_nak_retry_and_ack_required():
    sim = SimulatorTransport()
    sim.nak_next = 1
    device = Device(Settings(ack_timeout=0.06), sim)
    try:
        await device.connect()
        assert device.counters.naks == 1
        assert sim.commands[:2] == [b"\x31", b"\x31"]
        sim.omit_ack = True
        with pytest.raises(TimeoutError, match="ACK"):
            await device.command(replace(status_request(), attempts=1))
    finally:
        await device.close()


async def test_controlled_baud_detection():
    sim = SimulatorTransport(device_baud=38400)
    device = Device(Settings(ack_timeout=0.06), sim)
    try:
        await device.connect()
        assert device.info.baud == 38400
        assert device.counters.timeouts == 3
    finally:
        await device.close()


async def test_timeout_retry():
    sim = SimulatorTransport()
    device = Device(Settings(ack_timeout=0.06), sim)
    await device.connect()
    sim.silence_next = 1
    try:
        await device.command(status_request())
        assert device.counters.timeouts == 1
    finally:
        await device.close()


async def test_configuration_nak_is_not_retried_and_stops():
    class RejectConfig(SimulatorTransport):
        async def write(self, data):
            if data[4] == 0x77:
                self.nak_next = 1
            await super().write(data)

    sim = RejectConfig()
    device = Device(Settings(), sim)
    with pytest.raises(ProtocolError):
        await device.initialize()
    assert len([c for c in sim.commands if c[0] == 0x77]) == 1
    assert sim.commands[-1] == b"\x20\x25"
    assert device.state == State.FAULTED


async def test_index_wrap_and_dropped_scan_count():
    sim = SimulatorTransport(realtime=False)
    device = Device(Settings(), sim)
    await device.initialize()
    await wait_scan(device)
    sim.mode = 0x25
    await asyncio.sleep(0.03)
    device._last_telegram_index = 255
    sim._telegram_index = 0
    for frame in device.framer.feed(sim.scan_bytes()):
        device._handle(frame)
    assert device.counters.dropped_scans == 0
    sim._telegram_index = 3
    for frame in device.framer.feed(sim.scan_bytes()):
        device._handle(frame)
    assert device.counters.dropped_scans == 2
    await device.close()


@pytest.mark.parametrize(
    "resolution,angle,unit", [(1, 180, "cm"), (0.5, 180, "mm"), (0.25, 100, "mm")]
)
async def test_scan_configurations(resolution, angle, unit):
    sim = SimulatorTransport(realtime=False)
    device = Device(Settings(resolution=resolution, angle=angle, unit=unit), sim)
    await device.initialize()
    await wait_scan(device)
    assert device.latest.count == round(angle / resolution) + 1
    assert device.latest.unit == unit
    await device.close()
