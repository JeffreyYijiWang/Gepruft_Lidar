import pytest

from lms200.config import Settings


def test_compose_environment_numeric_literals(monkeypatch):
    for key, value in {
        "LMS_TRANSPORT": "simulator",
        "LMS_ANGLE": "180",
        "LMS_BAUD": "9600",
        "LMS_TARGET_BAUD": "38400",
        "LMS_RESOLUTION": "1.0",
        "LMS_AUTOSTART": "true",
    }.items():
        monkeypatch.setenv(key, value)
    settings = Settings()
    assert settings.angle == 180 and settings.baud == 9600
    assert settings.target_baud == 38400 and settings.autostart


def test_invalid_environment_baud_is_rejected(monkeypatch):
    monkeypatch.setenv("LMS_BAUD", "115200")
    with pytest.raises(ValueError):
        Settings()
