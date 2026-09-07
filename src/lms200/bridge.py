"""Native, protocol-agnostic serial bridge. See ADR 0002 for the lease/control wire format."""

import argparse
import asyncio
import hmac
import ipaddress
import json
import logging
import os
import signal
from contextlib import suppress
from typing import Any

from .transports.base import Transport
from .transports.serial import SerialTransport

log = logging.getLogger(__name__)


class SerialBridge:
    def __init__(
        self,
        serial: Transport,
        host: str = "127.0.0.1",
        data_port: int = 7000,
        control_port: int | None = 7001,
        token: str = "",
        high_speed: bool = False,
    ) -> None:
        if not ipaddress.ip_address(host).is_loopback and not token:
            raise ValueError("A non-loopback bridge requires LMS_BRIDGE_TOKEN and control mode")
        if token and control_port is None:
            raise ValueError("Tokens require the separate control channel")
        self.serial, self.host = serial, host
        self.data_port, self.control_port = data_port, control_port
        self.token, self.high_speed = token, high_speed
        self._server: asyncio.Server | None = None
        self._data_server: asyncio.Server | None = None
        self._lease = False
        self._peer: str | None = None
        self._data_task: asyncio.Task[None] | None = None
        self._clients: set[asyncio.Task[None]] = set()
        self._active_writer: asyncio.StreamWriter | None = None

    async def start(self) -> None:
        await self.serial.open()
        try:
            if self.control_port is None:
                self._data_server = await asyncio.start_server(
                    self._data, self.host, self.data_port
                )
                self.data_port = int(self._data_server.sockets[0].getsockname()[1])
            else:
                self._server = await asyncio.start_server(
                    self._control, self.host, self.control_port, limit=4096
                )
                self.control_port = int(self._server.sockets[0].getsockname()[1])
        except BaseException:
            await self.serial.close()
            raise

    async def _reply(self, writer: asyncio.StreamWriter, data: dict[str, Any]) -> None:
        writer.write(json.dumps(data).encode() + b"\n")
        await writer.drain()

    async def _control(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        current = asyncio.current_task()
        assert current is not None
        self._clients.add(current)
        owns = False
        try:
            message = json.loads(await asyncio.wait_for(reader.readline(), 5))
            token = str(message.get("token", ""))
            if (
                message.get("op") != "lease"
                or self._lease
                or not hmac.compare_digest(token.encode(), self.token.encode())
            ):
                await self._reply(writer, {"ok": False})
                return
            self._lease = owns = True
            self._peer = writer.get_extra_info("peername")[0]
            self._data_server = await asyncio.start_server(self._data, self.host, self.data_port)
            port = int(self._data_server.sockets[0].getsockname()[1])
            await self._reply(writer, {"ok": True, "data_port": port, "baud": self.serial.baud})
            # No secrets in logs. Lease lasts exactly as long as this control connection.
            log.info("Bridge lease acquired")
            while line := await reader.readline():
                message = json.loads(line)
                baud = message.get("baud")
                if message.get("op") == "baud" and baud in (9600, 19200, 38400, 500000):
                    if baud == 500000 and not self.high_speed:
                        await self._reply(writer, {"ok": False})
                        continue
                    await self.serial.set_baud(int(baud))
                    await self._reply(writer, {"ok": True, "baud": self.serial.baud})
                elif message.get("op") == "status":
                    await self._reply(writer, {"ok": True, "baud": self.serial.baud})
                else:
                    await self._reply(writer, {"ok": False})
        except (ValueError, OSError, TimeoutError):
            log.info("Bridge control connection ended or invalid request")
        finally:
            if owns:
                await self._end_lease()
            writer.close()
            with suppress(OSError):
                await writer.wait_closed()
            self._clients.discard(current)

    async def _data(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")[0]
        if self._data_task is not None or (
            self.control_port is not None and (not self._lease or peer != self._peer)
        ):
            writer.close()
            await writer.wait_closed()
            return
        self._data_task = asyncio.current_task()
        self._active_writer = writer
        if self.control_port is not None and self._data_server is not None:
            # Exactly one connection per lease, no bytes consumed for authentication.
            self._data_server.close()

        async def to_serial() -> None:
            while data := await reader.read(4096):
                await self.serial.write(data)

        async def from_serial() -> None:
            while True:
                data = await self.serial.read()
                if data:
                    writer.write(data)
                    await writer.drain()

        pumps = [asyncio.create_task(to_serial()), asyncio.create_task(from_serial())]
        try:
            done, _ = await asyncio.wait(pumps, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (OSError, EOFError):
            log.info("Bridge data connection ended")
        finally:
            for task in pumps:
                task.cancel()
            await asyncio.gather(*pumps, return_exceptions=True)
            writer.close()
            with suppress(OSError):
                await writer.wait_closed()
            self._active_writer = None
            self._data_task = None

    async def _end_lease(self) -> None:
        if self._data_server is not None:
            self._data_server.close()
            await self._data_server.wait_closed()
            self._data_server = None
        if self._data_task is not None:
            self._data_task.cancel()
            await asyncio.gather(self._data_task, return_exceptions=True)
        self._lease = False
        self._peer = None
        log.info("Bridge lease released")

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
        clients = list(self._clients)
        for task in clients:
            task.cancel()
        await asyncio.gather(*clients, return_exceptions=True)
        await self._end_lease()
        await self.serial.close()


async def run_bridge(args: argparse.Namespace) -> None:
    host, port = args.listen.rsplit(":", 1)
    if args.baud == 500000 and not args.high_speed:
        raise ValueError("500000 baud needs --high-speed after verifying an RS-422 adapter")
    bridge = SerialBridge(
        SerialTransport(args.port, args.baud),
        host,
        int(port),
        None if args.no_control else args.control_port,
        os.environ.get("LMS_BRIDGE_TOKEN", ""),
        args.high_speed,
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))
    await bridge.start()
    log.info("Bridge ready on %s, data port %s, control port %s", host, port, bridge.control_port)
    try:
        await stop.wait()
    finally:
        await bridge.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Native transparent serial bridge; local use only")
    parser.add_argument(
        "--port", required=True, help="COM3, /dev/cu.usbserial-..., /dev/ttyUSB0, or loop://"
    )
    parser.add_argument("--baud", type=int, choices=(9600, 19200, 38400, 500000), default=9600)
    parser.add_argument("--listen", default="127.0.0.1:7000")
    parser.add_argument("--control-port", type=int, default=7001)
    parser.add_argument(
        "--no-control", action="store_true", help="Loopback-only fixed-baud transparent mode"
    )
    parser.add_argument(
        "--high-speed", action="store_true", help="Explicit RS-422 adapter timing opt-in"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        asyncio.run(run_bridge(args))
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Bridge failed: {exc}\n")


if __name__ == "__main__":
    main()
