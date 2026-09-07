"""One owner of device I/O and commands, independent of FastAPI and the CLI."""

import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable
from contextlib import suppress
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from .config import Settings
from .protocol.commands import (
    Command,
    Mode,
    baud_rate,
    configuration_request,
    operating_mode,
    status_request,
    type_request,
    variant,
    write_configuration,
)
from .protocol.framing import Control, Frame, Framer
from .protocol.measurements import Scan, decode_scan
from .protocol.responses import (
    Configuration,
    DeviceError,
    DeviceStatus,
    ProtocolError,
    Response,
    confirm,
    decode_status,
    require_healthy,
    response,
)
from .transports import create_transport
from .transports.base import Transport
from .transports.replay import ReplayTransport

logger = logging.getLogger(__name__)


class State(StrEnum):
    DISCONNECTED = "disconnected"
    OPENING = "opening transport"
    DETECTING = "detecting baud rate"
    CONNECTED = "connected"
    STATUS = "requesting status"
    INSTALLATION = "entering configuration mode"
    CONFIGURING = "configuring scanner"
    BAUD = "changing baud rate"
    VERIFYING = "verifying configuration"
    STARTING = "starting measurement stream"
    STREAMING = "streaming"
    RECOVERING = "recovering"
    STOPPING = "stopping"
    FAULTED = "faulted"


@dataclass
class Counters:
    timeouts: int = 0
    naks: int = 0
    malformed: int = 0
    unexpected: int = 0
    dropped_scans: int = 0
    received_scans: int = 0


class Device:
    def __init__(
        self,
        settings: Settings,
        transport: Transport | None = None,
        on_scan: Callable[[Scan], None] | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport or create_transport(settings)
        self.on_scan = on_scan
        self.state = State.DISCONNECTED
        self.history: list[State] = [self.state]
        self.log: deque[str] = deque(maxlen=200)
        self.counters = Counters()
        self.framer = Framer()
        self.info: DeviceStatus | None = None
        self.model: str | None = None
        self.configuration: Configuration | None = None
        self.latest: Scan | None = None
        self.error: str | None = None
        self._events: asyncio.Queue[Control | Response | Exception] = asyncio.Queue(maxsize=64)
        self._reader: asyncio.Task[None] | None = None
        self._command_lock = asyncio.Lock()
        self._operation_lock = asyncio.Lock()
        self._changed = False
        self._open = False
        self._times: deque[float] = deque(maxlen=150)
        self._last_telegram_index: int | None = None
        self._stream_since = 0.0

    def note(self, message: str) -> None:
        # Only application-controlled descriptions; never raw commands/passwords/tokens.
        self.log.append(message)
        logger.info(message)

    def transition(self, state: State) -> None:
        self.state = state
        self.history.append(state)
        self.note(state.value)

    def _queue(self, event: Control | Response | Exception) -> None:
        if self._events.full():
            self._events.get_nowait()
            self.counters.unexpected += 1
        self._events.put_nowait(event)

    def _handle(self, event: Frame | Control) -> None:
        if isinstance(event, Control):
            self._queue(event)
            return
        try:
            reply = response(event, self.settings.address)
        except DeviceError as exc:
            self._queue(exc)
            return
        except ProtocolError:
            self.counters.malformed += 1
            return
        if reply.command == 0xB0:
            if self.configuration is None or self.info is None:
                return
            try:
                timestamp = (
                    self.transport.timestamp
                    if isinstance(self.transport, ReplayTransport)
                    else None
                )
                scan = decode_scan(
                    reply,
                    self.info.angle,
                    self.info.resolution,
                    self.configuration,
                    self.counters.received_scans + 1,
                    timestamp,
                )
                require_healthy(reply)
            except DeviceError as exc:
                self._queue(exc)
                self.error = str(exc)
                self.transition(State.FAULTED)
                return
            except (ProtocolError, ValueError):
                self.counters.malformed += 1
                return
            if scan.telegram_index is not None and self._last_telegram_index is not None:
                gap = (scan.telegram_index - self._last_telegram_index - 1) % 256
                self.counters.dropped_scans += gap
            self._last_telegram_index = scan.telegram_index
            self.counters.received_scans += 1
            self._times.append(time.monotonic())
            self.latest = scan
            if self.on_scan is not None:
                self.on_scan(scan)
        elif reply.command in (0x90, 0x91):
            self.note("Scanner startup/reset telegram received")
            if self.state == State.STREAMING:
                self.error = "Scanner reset during streaming; reconnect required"
                self.transition(State.FAULTED)
        else:
            self._queue(reply)

    async def _read_loop(self) -> None:
        last_bytes = time.monotonic()
        try:
            while True:
                data = await self.transport.read()
                now = time.monotonic()
                if data:
                    last_bytes = now
                    for event in self.framer.feed(data):
                        self._handle(event)
                elif self.framer.buffer and now - last_bytes > 0.25:
                    # 14ms scanner byte gaps (p24) plus USB/network scheduling margin.
                    for event in self.framer.expire():
                        self._handle(event)
                    last_bytes = now
                if self.state == State.STREAMING:
                    last_scan = self._times[-1] if self._times else self._stream_since
                    if now - last_scan > self.settings.stream_timeout:
                        self.counters.timeouts += 1
                        self.error = "Measurement timeout; reconnect required"
                        self.transition(State.FAULTED)
        except asyncio.CancelledError:
            raise
        except EOFError:
            if isinstance(self.transport, ReplayTransport):
                self.note("Replay complete")
                self.transition(State.CONNECTED)
            else:
                self.error = "Transport disconnected"
                self.transition(State.FAULTED)
            self._queue(EOFError("Transport ended"))
        except Exception:
            self.error = "Transport read failed; inspect host connection"
            self.transition(State.FAULTED)
            self._queue(OSError(self.error))

    async def command(self, cmd: Command) -> Response:
        async with self._command_lock:
            if cmd.mutates:
                self.settings.require_write()
                self._changed = True  # Includes ambiguous failures, so close attempts stop.
            for attempt in range(cmd.attempts):
                while not self._events.empty():
                    self._events.get_nowait()
                self.note(f"Sending {cmd.name} (attempt {attempt + 1})")
                await self.transport.write(cmd.telegram(self.settings.address))
                ack = False
                deadline = time.monotonic() + self.settings.ack_timeout
                try:
                    while True:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError
                        event = await asyncio.wait_for(self._events.get(), remaining)
                        if isinstance(event, Exception):
                            raise event
                        if event == Control.NAK:
                            self.counters.naks += 1
                            await asyncio.sleep(0.03)  # Listing §4.3 p24, minimum after NAK.
                            raise ProtocolError("NAK")
                        if event == Control.ACK:
                            if not ack:
                                ack = True
                                deadline = (
                                    time.monotonic() + cmd.timeout * self.settings.timeout_scale
                                )
                        elif isinstance(event, Response):
                            if event.command == cmd.response_id and ack:
                                confirm(event, cmd.payload)
                                return event
                            self.counters.unexpected += 1
                except TimeoutError:
                    self.counters.timeouts += 1
                    if attempt + 1 == cmd.attempts:
                        raise TimeoutError(
                            f"No {'response' if ack else 'ACK'} for {cmd.name}"
                        ) from None
                except DeviceError:
                    raise
                except ProtocolError:
                    if attempt + 1 == cmd.attempts:
                        raise
                await asyncio.sleep(0.03)
            raise ProtocolError("Command retry budget exhausted")

    async def _status(self) -> DeviceStatus:
        self.transition(State.STATUS)
        reply = await self.command(status_request())
        self.info = decode_status(reply)
        return self.info

    async def connect(self) -> None:
        if self._open:
            return
        self.error = None
        self._last_telegram_index = None
        self._times.clear()
        self.framer.reset()
        self.transition(State.OPENING)
        if self.settings.startup_wait:
            self.note("Waiting for externally powered scanner startup")
            await asyncio.sleep(self.settings.startup_wait)
        await self.transport.open()
        self._open = True
        if isinstance(self.transport, ReplayTransport):
            meta = self.transport.metadata
            self.configuration = Configuration(bytes.fromhex(meta["configuration_hex"]))
            self.info = DeviceStatus(**meta["device_status"])
            self.model = str(meta.get("model", "recorded LMS200"))
            self.transition(State.CONNECTED)
            return
        self._reader = asyncio.create_task(self._read_loop())
        self.transition(State.DETECTING)
        rates = [self.transport.baud]
        if self.settings.detect_baud and self.transport.can_set_baud:
            rates = [9600, 38400, 19200] + ([500000] if self.settings.high_speed else [])
        for rate in rates:
            await self.transport.set_baud(rate)
            self.framer.reset()
            try:
                await self._status()
                break
            except (TimeoutError, ProtocolError):
                self.note(f"No valid status at {rate} baud")
        else:
            raise TimeoutError("No scanner found at the permitted baud rates")
        assert self.info is not None
        if self.info.baud != self.transport.baud:
            raise ProtocolError("Status baud disagrees with adapter baud")
        self.transition(State.CONNECTED)
        identity = await self.command(type_request())
        try:
            self.model = identity.data.decode("ascii").strip()
        except UnicodeDecodeError as exc:
            raise ProtocolError("Invalid scanner identity") from exc
        self.configuration = Configuration((await self.command(configuration_request())).data)
        self.transition(State.CONNECTED)

    async def initialize(self, start_stream: bool = True) -> None:
        self.settings.require_write()
        async with self._operation_lock:
            if self.state == State.STREAMING:
                return
            try:
                await self.connect()
                if isinstance(self.transport, ReplayTransport):
                    self.transition(State.STREAMING)
                    self._stream_since = time.monotonic()
                    self._reader = asyncio.create_task(self._read_loop())
                    return
                assert self.info is not None and self.configuration is not None
                if self.info.device_error:
                    raise DeviceError("B1 reports a defective scanner")
                if self.model is None or not self.model.startswith(
                    ("LMS200;30106", "LMS200-30106")
                ):
                    raise DeviceError("Configuration is limited to LMS200-30106")
                # Stop pre-existing streaming before settings commands, Quick Manual p12/14.
                await self.command(operating_mode(Mode.ON_REQUEST))
                desired = self.configuration.updated(self.settings.unit, self.settings.indices)
                geometry_changes = (self.info.angle, self.info.resolution) != (
                    self.settings.angle,
                    self.settings.resolution,
                )
                changes = desired.raw != self.configuration.raw
                if changes or geometry_changes:
                    self.transition(State.INSTALLATION)
                    await self.command(
                        operating_mode(Mode.INSTALLATION, self.settings.password.get_secret_value())
                    )
                if (
                    self.settings.target_baud is not None
                    and self.settings.target_baud != self.transport.baud
                ):
                    self.transition(State.BAUD)
                    await self.command(baud_rate(self.settings.target_baud))
                    await self.transport.set_baud(self.settings.target_baud)
                    await self._status()
                    if self.info.baud != self.settings.target_baud:
                        raise ProtocolError("Scanner did not confirm new baud")
                self.transition(State.CONFIGURING)
                if geometry_changes:
                    await self.command(variant(self.settings.angle, self.settings.resolution))
                if changes:
                    await self.command(write_configuration(desired.raw))
                self.transition(State.VERIFYING)
                self.configuration = Configuration(
                    (await self.command(configuration_request())).data
                )
                await self._status()
                if (
                    self.configuration.raw != desired.raw
                    or self.info.angle != self.settings.angle
                    or self.info.resolution != self.settings.resolution
                    or self.info.unit != desired.unit
                    or self.info.measuring_mode != desired.mode
                ):
                    raise ProtocolError("Scanner configuration readback did not match")
                await self.command(operating_mode(Mode.ON_REQUEST))
                if start_stream:
                    self.transition(State.STARTING)
                    await self.command(operating_mode(Mode.CONTINUOUS))
                    self._stream_since = time.monotonic()
                    self.transition(State.STREAMING)
                else:
                    self.transition(State.CONNECTED)
            except BaseException:
                await self._close_unlocked()
                self.transition(State.FAULTED)
                raise

    async def _close_unlocked(self) -> None:
        if not self._open:
            return
        self.transition(State.STOPPING)
        if self._changed and not isinstance(self.transport, ReplayTransport):
            try:
                await self.command(operating_mode(Mode.ON_REQUEST))
                self.note("Scanner confirmed output-on-request (20/25)")
            except Exception:
                self.note(
                    "Stop was not confirmed; scanner state unknown, check connection before reuse"
                )
        if self._reader is not None:
            self._reader.cancel()
            with suppress(asyncio.CancelledError):
                await self._reader
            self._reader = None
        await self.transport.close()
        self._open = False
        self._changed = False
        self.transition(State.DISCONNECTED)

    async def close(self) -> None:
        async with self._operation_lock:
            await self._close_unlocked()

    async def reconnect(self) -> None:
        self.transition(State.RECOVERING)
        await self.close()
        await self.initialize()

    def metadata(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "baud": self.transport.baud,
            "device_status": asdict(self.info) if self.info else None,
            "configuration_hex": self.configuration.raw.hex() if self.configuration else None,
            "transport": self.settings.transport,
        }

    def snapshot(self) -> dict[str, Any]:
        now = time.monotonic()
        recent = [t for t in self._times if now - t <= 3]
        received_hz = (len(recent) - 1) / (recent[-1] - recent[0]) if len(recent) > 1 else 0
        count = self.latest.count if self.latest else 0
        resolution = self.info.resolution if self.info else self.settings.resolution
        return {
            "state": self.state,
            "error": self.error,
            "settings": self.settings.public(),
            **self.metadata(),
            "counters": asdict(self.counters),
            "framing": asdict(self.framer.stats),
            "nominal_mirror_hz": 75,
            "nominal_complete_scan_hz": 75 * resolution,
            "received_scan_hz": round(received_hz, 2),
            "points": count,
            "serial_ceiling_hz": round(self.transport.baud / (10 * (count * 2 + 12)), 2)
            if count
            else None,
            "log": list(self.log),
        }
