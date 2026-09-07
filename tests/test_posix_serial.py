"""Linux/macOS PTY integration: the actual pyserial path, with synthetic LMS on the peer."""

import asyncio
import os
import select

import pytest

from lms200.config import HardwareConsent, Settings
from lms200.state_machine import Device
from lms200.transports.serial import SerialTransport
from lms200.transports.simulator import SimulatorTransport

pytestmark = [
    pytest.mark.posix,
    pytest.mark.skipif(os.name != "posix", reason="POSIX PTY required"),
]


async def test_direct_linux_serial_with_virtual_lms():
    master, slave = os.openpty()
    sim = SimulatorTransport(realtime=False)
    await sim.open()
    settings = Settings(
        transport="serial",
        serial_port=os.ttyname(slave),
        read_only=False,
        consent=HardwareConsent(
            power_connector_identified=True,
            data_connector_identified=True,
            serial_standard_selected=True,
            adapter_voltage_verified=True,
        ),
    )
    device = Device(settings, SerialTransport(os.ttyname(slave)))

    async def host_commands():
        while True:
            ready, _, _ = await asyncio.to_thread(select.select, [master], [], [], 0.02)
            if ready:
                await sim.write(os.read(master, 4096))

    async def scanner_output():
        while True:
            data = await sim.read()
            if data:
                os.write(master, data)

    tasks = [asyncio.create_task(host_commands()), asyncio.create_task(scanner_output())]
    try:
        await device.initialize()
        async with asyncio.timeout(3):
            while device.latest is None:
                await asyncio.sleep(0.01)
        assert device.latest.count == 181
    finally:
        await device.close()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await sim.close()
        os.close(master)
        os.close(slave)
    assert sim.commands[-1] == b"\x20\x25"
