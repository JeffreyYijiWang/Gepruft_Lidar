"""One native RS-232 status request at 9600 8-N-1; no device initialization.

Telegram Listing §7.6 pp52–57, §4 pp21–25, §9 p107; Quick Manual C.2 p9.
This commissioning path deliberately has no transport/baud/configuration options.
"""

import json
import logging
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import serial

from .protocol.commands import status_request
from .protocol.crc import crc16
from .protocol.framing import Control, Frame, Framer
from .protocol.responses import ProtocolError, decode_status, response


def probe_status(port: str, log_path: Path) -> dict[str, Any]:
    """Log one status exchange, close on every exit, and return factual diagnostics.

    TX counts mean bytes accepted by the host driver, not a line-analyzer capture.
    No retry, baud search, model/config read, stop, or password telegram is possible.
    """
    report: dict[str, Any] = {
        "port": port,
        "serial_standard": "rs232",
        "baud": 9600,
        "data_bits": 8,
        "parity": "N",
        "stop_bits": 1,
        "ack_wait_seconds": 3.0,
        "response_wait_seconds": 3.0,
        "listen_seconds": 0.0,
        "port_opened": False,
        "port_closed": True,
        "success": False,
        "ack": False,
        "tx_bytes": 0,
        "rx_bytes": 0,
        "tx_hex": "",
        "rx_hex": "",
        "response": None,
        "error": None,
    }
    framer = Framer()
    received = bytearray()
    listen_started: float | None = None
    request = status_request().telegram(0)
    # Independent published vector: Quick Manual C.2 p9.
    if request != bytes.fromhex("02 00 01 00 31 15 12"):
        raise ValueError("Status request does not match the published golden vector")
    with log_path.open("x", encoding="utf-8") as log:

        def emit(kind: str, **values: Any) -> None:
            log.write(
                json.dumps({"time": datetime.now(UTC).isoformat(), "event": kind, **values}) + "\n"
            )
            log.flush()

        # Construct closed so control-line values are set before opening the adapter.
        device = serial.Serial(
            port=None,
            baudrate=9600,
            bytesize=8,
            parity="N",
            stopbits=1,
            timeout=0.02,
            write_timeout=0.25,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        )
        device.port = port
        device.dtr = False
        device.rts = False
        try:
            emit("opening", port=port, baud=9600, format="8-N-1", standard="rs232")
            device.open()
            report["port_opened"], report["port_closed"] = True, False
            device.reset_input_buffer()
            emit("stale_input_cleared")
            emit("tx_attempt", hex=request.hex(" ").upper())
            # If the driver raises mid-write, actual transmitted byte count is unknown.
            report["tx_bytes"] = None
            written = device.write(request)
            report["tx_bytes"] = written
            report["tx_hex"] = request[:written].hex(" ").upper()
            emit("tx_accepted_by_driver", count=written, hex=report["tx_hex"])
            logging.info("TX %s", report["tx_hex"])
            if written != len(request):
                raise OSError("Incomplete status-request write")
            # TL p24 specifies ACK within 60ms. This diagnostic deliberately listens
            # for 3 seconds even without ACK to capture delayed USB/serial bytes.
            listen_started = time.monotonic()
            deadline = listen_started + report["ack_wait_seconds"]
            emit("listening", ack_wait_seconds=report["ack_wait_seconds"])
            while time.monotonic() < deadline:
                data = device.read(max(1, min(4096, device.in_waiting)))
                if not data:
                    continue
                received.extend(data)
                emit("rx", count=len(data), hex=data.hex(" ").upper())
                logging.info("RX %s", data.hex(" ").upper())
                for event in framer.feed(data):
                    if event == Control.NAK:
                        raise ProtocolError("NAK received; no retry attempted")
                    if event == Control.ACK:
                        if not report["ack"]:
                            report["ack"] = True
                            deadline = time.monotonic() + report["response_wait_seconds"]
                        continue
                    assert isinstance(event, Frame)
                    reply = response(event)
                    frame_info = {
                        "address_hex": f"{event.address:02X}",
                        "command_hex": f"{event.command:02X}",
                        "payload_length": len(event.payload),
                        "crc_expected_hex": f"{crc16(event.raw[:-2]):04X}",
                        "crc_received_hex": f"{int.from_bytes(event.raw[-2:], 'little'):04X}",
                        "crc_valid": True,
                        "status_byte": asdict(reply.status),
                    }
                    emit("validated_frame", **frame_info)
                    if reply.command != 0xB1:
                        continue
                    report["response"] = frame_info
                    frame_info["device_status"] = asdict(decode_status(reply))
                    frame_info["device_type"] = reply.status.source
                    frame_info["exact_model"] = None  # BA model query intentionally not sent.
                    if not report["ack"]:
                        raise ProtocolError("B1 received without preceding ACK")
                    report["success"] = True
                    return report
            raise TimeoutError("No complete ACK + valid B1 status response; no retry attempted")
        except KeyboardInterrupt:
            report["error"] = "Interrupted; no further command sent"
        except (OSError, ProtocolError, ValueError) as exc:
            report["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            if listen_started is not None:
                report["listen_seconds"] = round(time.monotonic() - listen_started, 6)
            try:
                device.close()  # Closing this handle never sends an LMS stop command.
            finally:
                report["port_closed"] = not device.is_open
                report["rx_bytes"] = len(received)
                report["rx_hex"] = received.hex(" ").upper()
                report["framing"] = asdict(framer.stats)
                report["trailing_partial_hex"] = framer.buffer.hex(" ").upper()
                emit("result", **report)
    return report
