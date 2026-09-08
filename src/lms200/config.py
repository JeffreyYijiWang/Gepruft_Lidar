"""Validated configuration and explicit physical-hardware consent."""

from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .protocol.commands import validate_geometry


class HardwareConsent(BaseModel):
    power_connector_identified: bool = False
    data_connector_identified: bool = False
    serial_standard_selected: bool = False
    adapter_voltage_verified: bool = False
    rs422_pins_7_8_bridged: bool = False

    def require(self, standard: str) -> None:
        if not all(
            (
                self.power_connector_identified,
                self.data_connector_identified,
                self.serial_standard_selected,
                self.adapter_voltage_verified,
            )
        ):
            raise ValueError(
                "Confirm power/data connectors, serial standard, and adapter/cable voltages"
            )
        if standard == "rs422" and not self.rs422_pins_7_8_bridged:
            raise ValueError("Confirm scanner data pins 7 and 8 are bridged for RS-422")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LMS_", env_nested_delimiter="__", extra="ignore")
    transport: Literal["serial", "tcp", "simulator", "replay"] = "simulator"
    serial_port: str | None = None
    host: str = "host.docker.internal"
    tcp_port: int = Field(default=7000, ge=1, le=65535)
    control_port: int | None = Field(default=None, ge=1, le=65535)
    token: SecretStr = SecretStr("")
    baud: Literal[9600, 19200, 38400, 500000] = 9600
    detect_baud: bool = True
    target_baud: Literal[9600, 19200, 38400, 500000] | None = None
    serial_standard: Literal["rs232", "rs422"] = "rs232"
    high_speed: bool = False
    address: int = Field(default=0, ge=0, le=127)
    angle: Literal[100, 180] = 180
    resolution: float = 1.0
    unit: Literal["mm", "cm"] = "mm"
    indices: bool = True
    read_only: bool = True
    consent: HardwareConsent = Field(default_factory=HardwareConsent)
    password: SecretStr = SecretStr("SICK_LMS")
    startup_wait: float = Field(default=0, ge=0, le=60)
    ack_timeout: float = Field(default=0.25, ge=0.06, le=5)
    timeout_scale: float = Field(default=1, gt=0, le=10)
    stream_timeout: float = Field(default=4, ge=1, le=60)
    recording_dir: Path = Path("recordings")
    replay_path: Path | None = None
    replay_speed: float = Field(default=1, gt=0, le=1000)
    autostart: bool = False
    web_host: str = "127.0.0.1"
    web_port: int = Field(default=8000, ge=1, le=65535)

    @field_validator("baud", "target_baud", "angle", mode="before")
    @classmethod
    def numeric_environment_values(cls, value: object) -> object:
        # Pydantic Literal[int] checks identity before coercion; environment values are strings.
        return int(value) if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_settings(self) -> Self:
        validate_geometry(self.angle, self.resolution)
        if self.high_speed and self.serial_standard != "rs422":
            raise ValueError("High-speed detection requires RS-422")
        if 500000 in (self.baud, self.target_baud) and not (
            self.high_speed and self.serial_standard == "rs422"
        ):
            raise ValueError("500000 baud requires explicit high_speed and RS-422")
        if (
            self.transport == "tcp"
            and self.control_port is None
            and self.target_baud not in (None, self.baud)
        ):
            raise ValueError("Baud switching needs the host bridge control port")
        return self

    @property
    def physical(self) -> bool:
        return self.transport in ("serial", "tcp")

    def require_write(self) -> None:
        if self.physical:
            if self.read_only:
                raise ValueError(
                    "Read-only mode: explicitly enable writes and confirm hardware checklist"
                )
            self.consent.require(self.serial_standard)

    def public(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"password", "token"})
