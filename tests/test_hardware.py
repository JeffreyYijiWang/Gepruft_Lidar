"""Read-only physical probe, disabled unless explicitly requested by environment."""

import os

import pytest

from lms200.config import Settings
from lms200.state_machine import Device

pytestmark = [
    pytest.mark.hardware,
    pytest.mark.skipif(
        not os.environ.get("LMS_HARDWARE_TEST_PORT"), reason="Physical hardware tests are opt-in"
    ),
]


async def test_physical_readonly_probe():
    device = Device(
        Settings(
            transport="serial", serial_port=os.environ["LMS_HARDWARE_TEST_PORT"], read_only=True
        )
    )
    try:
        await device.connect()
        assert device.info is not None and device.model.startswith("LMS200")
    finally:
        await device.close()
