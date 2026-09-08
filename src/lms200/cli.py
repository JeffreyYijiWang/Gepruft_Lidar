"""Native CLI; transport arguments are shared with the local API server."""

import argparse
import asyncio
import json
import logging
import signal
from pathlib import Path
from typing import Any

import uvicorn

from .config import HardwareConsent, Settings
from .service import Service
from .state_machine import State
from .transports.serial import ports


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="SICK LMS200-30106 acquisition and diagnostics")
    sub = root.add_subparsers(dest="command", required=True)
    sub.add_parser("ports", help="List native serial devices")
    single = sub.add_parser(
        "probe-status", help="One native RS-232 status request, fixed 9600 8-N-1"
    )
    single.add_argument("--port", required=True, help="Verified native COM/tty port")
    single.add_argument("--log", type=Path, required=True, help="New JSONL hexadecimal transcript")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--transport", choices=("simulator", "serial", "tcp", "replay"))
    common.add_argument("--port", help="Serial path/COM name, or TCP data port")
    common.add_argument("--host")
    common.add_argument("--control-port", type=int)
    common.add_argument("--baud", type=int, choices=(9600, 19200, 38400, 500000))
    common.add_argument("--target-baud", type=int, choices=(9600, 19200, 38400, 500000))
    common.add_argument("--fixed-baud", action="store_true", help="Disable baud detection")
    common.add_argument("--serial-standard", choices=("rs232", "rs422"))
    common.add_argument(
        "--high-speed", action="store_true", help="Opt in to 500k RS-422 host byte pacing"
    )
    common.add_argument("--angle", type=int, choices=(100, 180))
    common.add_argument("--resolution", type=float, choices=(0.25, 0.5, 1.0))
    common.add_argument("--unit", choices=("mm", "cm"))
    common.add_argument("--read-only", "--probe-only", action="store_true")
    common.add_argument("--allow-writes", action="store_true")
    common.add_argument(
        "--confirm-hardware",
        action="store_true",
        help=(
            "Confirm power and data connectors identified, serial standard selected, adapter/cable "
            "voltages verified; see docs/HARDWARE.md"
        ),
    )
    common.add_argument("--confirm-rs422-jumper", action="store_true")
    common.add_argument("--startup-wait", type=float, help="Host wait in seconds, up to 60")
    common.add_argument("--file", type=Path, dest="replay_path")
    common.add_argument("--replay-speed", type=float)
    common.add_argument("--recording-dir", type=Path)
    for name in ("probe", "status", "diagnose", "configure", "stream", "record", "replay", "serve"):
        command = sub.add_parser(name, parents=[common])
        if name in ("stream", "record", "replay"):
            command.add_argument(
                "--duration", type=float, default=0, help="Seconds; 0 runs until Ctrl+C"
            )
            command.add_argument("--output", type=Path, help="Optional JSONL export path")
        if name == "serve":
            command.add_argument("--web-host")
            command.add_argument("--web-port", type=int)
            command.add_argument("--autostart", action="store_true")
    return root


def settings_from(args: argparse.Namespace) -> Settings:
    values: dict[str, Any] = {}
    for name in (
        "transport",
        "host",
        "control_port",
        "baud",
        "target_baud",
        "serial_standard",
        "angle",
        "resolution",
        "unit",
        "startup_wait",
        "replay_path",
        "replay_speed",
        "recording_dir",
        "web_host",
        "web_port",
    ):
        if getattr(args, name, None) is not None:
            values[name] = getattr(args, name)
    if args.command == "replay":
        values["transport"] = "replay"
    if args.high_speed:
        values["high_speed"] = True
    preliminary = Settings(**values)
    if args.port:
        values["tcp_port" if preliminary.transport == "tcp" else "serial_port"] = (
            int(args.port) if preliminary.transport == "tcp" else args.port
        )
    if args.fixed_baud:
        values["detect_baud"] = False
    if args.high_speed:
        values["high_speed"] = True
    if args.allow_writes:
        values["read_only"] = False
    if args.read_only or args.command in ("probe", "status", "diagnose"):
        values["read_only"] = True
    if args.confirm_hardware:
        values["consent"] = HardwareConsent(
            power_connector_identified=True,
            data_connector_identified=True,
            serial_standard_selected=True,
            adapter_voltage_verified=True,
            rs422_pins_7_8_bridged=args.confirm_rs422_jumper,
        )
    if getattr(args, "autostart", False):
        values["autostart"] = True
    return Settings(**values)


async def run(args: argparse.Namespace, settings: Settings) -> None:
    service = Service(settings)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))
    output = None
    queue = service.subscribe()
    try:
        if args.command in ("probe", "status", "diagnose"):
            await service.device.connect()
            print(json.dumps(service.snapshot(), indent=2))
            return
        if args.read_only:
            await service.device.connect()
            print(json.dumps(service.snapshot(), indent=2))
            return
        await service.device.initialize(start_stream=args.command != "configure")
        if args.command == "configure":
            print(json.dumps(service.snapshot(), indent=2))
            return
        if args.command == "record":
            name = await service.start_recording()
            logging.info("Recording %s", name)
        if args.output:
            output = args.output.open("x", encoding="utf-8")
        deadline = loop.time() + args.duration if args.duration > 0 else float("inf")
        while not stop.is_set() and loop.time() < deadline:
            if service.device.state == State.FAULTED:
                raise OSError(service.device.error or "Scanner faulted")
            if service.device.state != State.STREAMING and queue.empty():
                break
            try:
                scan = await asyncio.wait_for(queue.get(), 0.1)
                data = json.dumps(
                    {"metadata": service.device.metadata(), "scan": scan.to_dict()},
                    separators=(",", ":"),
                    allow_nan=False,
                )
                if output:
                    output.write(data + "\n")
                elif args.command != "record":
                    print(data)
            except TimeoutError:
                continue
    finally:
        await service.close()
        if output:
            output.close()


def main() -> None:
    cli = parser()
    args = cli.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.command == "ports":
        print(json.dumps(ports(), indent=2))
        return
    try:
        if args.command == "probe-status":
            from .status_probe import probe_status

            def interrupt(*_: Any) -> None:
                raise KeyboardInterrupt

            previous = signal.signal(signal.SIGTERM, interrupt)
            try:
                result = probe_status(args.port, args.log)
            finally:
                signal.signal(signal.SIGTERM, previous)
            print(json.dumps(result, indent=2))
            if not result["success"]:
                cli.exit(1)
            return
        settings = settings_from(args)
        if args.command == "serve":
            from .api.app import create_app

            uvicorn.run(
                create_app(settings),
                host=settings.web_host,
                port=settings.web_port,
                timeout_graceful_shutdown=15,
            )
        else:
            asyncio.run(run(args, settings))
    except KeyboardInterrupt:
        pass
    except (ValueError, OSError, TimeoutError) as exc:
        # Validation messages can embed secret input values, so do not print raw exceptions.
        cli.exit(1, f"{type(exc).__name__}: request failed; check arguments and diagnostics\n")


if __name__ == "__main__":
    main()
