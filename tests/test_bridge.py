import asyncio

import pytest

from lms200.bridge import SerialBridge
from lms200.config import HardwareConsent, Settings
from lms200.state_machine import Device
from lms200.transports.serial import SerialTransport
from lms200.transports.simulator import SimulatorTransport
from lms200.transports.tcp import TCPTransport


async def test_loopback_is_byte_transparent_and_controlled():
    serial = SerialTransport("loop://", 9600)
    bridge = SerialBridge(serial, data_port=0, control_port=0, token="test-only", high_speed=True)
    await bridge.start()
    tcp = TCPTransport("127.0.0.1", 0, control_port=bridge.control_port, token="test-only")
    try:
        await tcp.open()
        payload = bytes(range(256)) * 3  # Includes ACK, NAK, STX, LF, JSON punctuation.
        await tcp.write(payload)
        received = bytearray()
        async with asyncio.timeout(5):
            while len(received) < len(payload):
                received.extend(await tcp.read())
        assert bytes(received) == payload
        for rate in (38400, 500000, 9600):
            await tcp.set_baud(rate)
            assert serial.baud == tcp.baud == rate
            assert serial.serial.baudrate == rate
            await tcp.write(b"\x00\xff\x02\x06")
            data = bytearray()
            async with asyncio.timeout(3):
                while len(data) < 4:
                    data.extend(await tcp.read())
            assert data == b"\x00\xff\x02\x06"
    finally:
        await tcp.close()
        await bridge.close()


async def test_authentication_and_exclusive_lease():
    bridge = SerialBridge(SerialTransport("loop://"), data_port=0, control_port=0, token="correct")
    await bridge.start()
    wrong = TCPTransport("127.0.0.1", 0, control_port=bridge.control_port, token="wrong")
    first = TCPTransport("127.0.0.1", 0, control_port=bridge.control_port, token="correct")
    second = TCPTransport("127.0.0.1", 0, control_port=bridge.control_port, token="correct")
    try:
        with pytest.raises(OSError):
            await wrong.open()
        await first.open()
        with pytest.raises(OSError):
            await second.open()
        assert bridge._lease
    finally:
        await first.close()
        await second.close()
        await wrong.close()
        await bridge.close()


@pytest.mark.parametrize("baud", [38400, 500000])
async def test_simulator_through_bridge_complete_baud_sequence(baud):
    sim = SimulatorTransport(realtime=False)
    bridge = SerialBridge(sim, data_port=0, control_port=0, token="test", high_speed=True)
    await bridge.start()
    tcp = TCPTransport("127.0.0.1", 0, control_port=bridge.control_port, token="test")
    settings = Settings(
        transport="tcp",
        control_port=bridge.control_port,
        target_baud=baud,
        high_speed=baud == 500000,
        serial_standard="rs422",
        read_only=False,
        consent=HardwareConsent(
            power_connector_identified=True,
            data_connector_identified=True,
            serial_standard_selected=True,
            adapter_voltage_verified=True,
            rs422_pins_7_8_bridged=True,
        ),
    )
    device = Device(settings, tcp)
    try:
        await device.initialize()
        async with asyncio.timeout(3):
            while device.latest is None:
                await asyncio.sleep(0.01)
        assert sim.baud == sim.device_baud == tcp.baud == baud
        assert device.latest.count == 181
    finally:
        await device.close()
        await bridge.close()
    assert sim.commands[-1] == b"\x20\x25"


async def test_uncontrolled_bridge_cannot_switch_baud():
    transport = TCPTransport("localhost", 7000, baud=38400)
    await transport.set_baud(38400)
    with pytest.raises(ValueError):
        await transport.set_baud(9600)


def test_public_bridge_requires_access_protection():
    with pytest.raises(ValueError):
        SerialBridge(SerialTransport("loop://"), host="0.0.0.0")


async def test_high_speed_host_byte_pacing(monkeypatch):
    sleeps = []
    transport = SerialTransport("loop://", 500000)
    await transport.open()
    monkeypatch.setattr("lms200.transports.serial.time.sleep", sleeps.append)
    try:
        await transport.write(b"\x02\x00\x01\x00\x31\x15\x12")
        assert len(sleeps) == 7 and all(delay >= 0.000055 for delay in sleeps)
    finally:
        await transport.close()
