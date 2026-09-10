"""Read the driver DCB on pyserial's existing Windows handle; never open a port.

Microsoft DCB/GetCommState documentation defines the enum constants. A successful
readback is driver evidence, not measurement of the connector's electrical signal.
"""

import ctypes
import logging
import os
from collections.abc import Callable
from typing import Any

import serial

log = logging.getLogger(__name__)


def read_windows_dcb(device: serial.Serial) -> dict[str, Any]:
    if os.name != "nt":
        raise OSError("GetCommState is only available on native Windows")
    from serial import win32 as serial_win32

    # types-pyserial omits several constants which serialwin32 itself uses.
    win32: Any = serial_win32

    handle = getattr(device, "_port_handle", None)
    if not device.is_open or not handle:
        raise OSError("No open native Windows pyserial handle; readback unavailable")
    actual = win32.DCB()
    actual.DCBlength = ctypes.sizeof(actual)
    if not win32.GetCommState(handle, ctypes.byref(actual)):
        code = win32.GetLastError()  # Capture before any other Windows call.
        raise ctypes.WinError(code)
    fields = (
        "DCBlength",
        "BaudRate",
        "ByteSize",
        "Parity",
        "StopBits",
        "fBinary",
        "fParity",
        "fOutxCtsFlow",
        "fOutxDsrFlow",
        "fDtrControl",
        "fDsrSensitivity",
        "fTXContinueOnXoff",
        "fOutX",
        "fInX",
        "fErrorChar",
        "fNull",
        "fRtsControl",
        "fAbortOnError",
    )
    result: dict[str, Any] = {name: int(getattr(actual, name)) for name in fields}
    result.update(
        handle_hex=hex(handle),
        Parity_symbol={
            win32.NOPARITY: "NOPARITY",
            win32.ODDPARITY: "ODDPARITY",
            win32.EVENPARITY: "EVENPARITY",
            win32.MARKPARITY: "MARKPARITY",
            win32.SPACEPARITY: "SPACEPARITY",
        }.get(actual.Parity, "UNKNOWN"),
        StopBits_symbol={
            win32.ONESTOPBIT: "ONESTOPBIT",
            win32.ONE5STOPBITS: "ONE5STOPBITS",
            win32.TWOSTOPBITS: "TWOSTOPBITS",
        }.get(actual.StopBits, "UNKNOWN"),
        stop_bit_count={
            win32.ONESTOPBIT: 1,
            win32.ONE5STOPBITS: 1.5,
            win32.TWOSTOPBITS: 2,
        }.get(actual.StopBits),
        DtrControl_symbol={
            win32.DTR_CONTROL_DISABLE: "DTR_CONTROL_DISABLE",
            win32.DTR_CONTROL_ENABLE: "DTR_CONTROL_ENABLE",
            win32.DTR_CONTROL_HANDSHAKE: "DTR_CONTROL_HANDSHAKE",
        }.get(actual.fDtrControl, "UNKNOWN"),
        RtsControl_symbol={
            win32.RTS_CONTROL_DISABLE: "RTS_CONTROL_DISABLE",
            win32.RTS_CONTROL_ENABLE: "RTS_CONTROL_ENABLE",
            win32.RTS_CONTROL_HANDSHAKE: "RTS_CONTROL_HANDSHAKE",
            win32.RTS_CONTROL_TOGGLE: "RTS_CONTROL_TOGGLE",
        }.get(actual.fRtsControl, "UNKNOWN"),
    )
    return result


def mismatches(actual: dict[str, Any], baud: int) -> dict[str, Any]:
    expected = {
        "BaudRate": baud,
        "ByteSize": 8,
        "Parity_symbol": "NOPARITY",
        "StopBits_symbol": "ONESTOPBIT",
        "fParity": 0,
        "fBinary": 1,
        "fOutxCtsFlow": 0,
        "fOutxDsrFlow": 0,
        "fDsrSensitivity": 0,
        "fOutX": 0,
        "fInX": 0,
        "fNull": 0,
        "fErrorChar": 0,
        "fAbortOnError": 0,
    }
    differences = {
        key: {"expected": value, "actual": actual.get(key)}
        for key, value in expected.items()
        if actual.get(key) != value
    }
    # Asserted DTR/RTS lines are not themselves flow control; handshake modes are.
    for key in ("DtrControl_symbol", "RtsControl_symbol"):
        if actual.get(key) not in (
            "DTR_CONTROL_DISABLE",
            "DTR_CONTROL_ENABLE",
            "RTS_CONTROL_DISABLE",
            "RTS_CONTROL_ENABLE",
        ):
            differences[key] = {"expected": "static ENABLE or DISABLE", "actual": actual.get(key)}
    return differences


def verify_windows_serial(
    device: serial.Serial, baud: int, stage: str, emit: Callable[..., None] | None = None
) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "stage": stage,
        "requested_baud": baud,
        "pyserial_cached_settings": device.get_settings(),
        "pyserial_dtr": device.dtr,
        "pyserial_rts": device.rts,
        "api": "GetCommState",
        "confirmed": False,
    }
    # Portable production transports still work; do not call non-Windows evidence confirmed.
    if os.name != "nt":
        evidence["available"] = False
        evidence["reason"] = "Not native Windows"
        return evidence
    try:
        evidence["windows_dcb"] = read_windows_dcb(device)
        evidence["mismatches"] = mismatches(evidence["windows_dcb"], baud)
        evidence["confirmed"] = not evidence["mismatches"]
    except OSError as exc:
        evidence["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
            "winerror": getattr(exc, "winerror", None),
            "errno": exc.errno,
        }
        if emit is not None:
            emit("windows_dcb_readback", **evidence)
        log.error("DCB readback failed: %s", evidence)
        raise
    if emit is not None:
        emit("windows_dcb_readback", **evidence)
    if not evidence["confirmed"]:
        raise OSError(f"Windows DCB differs from required {baud}/8-N-1/no-flow: {evidence}")
    return evidence
