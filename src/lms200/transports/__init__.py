"""Transport factory; callers may inject any Transport implementation."""

from lms200.config import Settings

from .base import Transport
from .serial import SerialTransport, ports
from .simulator import SimulatorTransport
from .tcp import TCPTransport


def create_transport(settings: Settings) -> Transport:
    if settings.transport == "simulator":
        return SimulatorTransport(settings.baud)
    if settings.transport == "serial":
        port = settings.serial_port
        if port is None:
            devices = ports()
            if len(devices) != 1:
                raise ValueError(
                    "Specify --port; automatic selection requires exactly one serial device"
                )
            port = str(devices[0]["device"])
        return SerialTransport(port, settings.baud)
    if settings.transport == "tcp":
        return TCPTransport(
            settings.host,
            settings.tcp_port,
            settings.baud,
            settings.control_port,
            settings.token.get_secret_value(),
        )
    from .replay import ReplayTransport

    if settings.replay_path is None:
        raise ValueError("Replay requires --file or LMS_REPLAY_PATH")
    return ReplayTransport(settings.replay_path, settings.replay_speed)
