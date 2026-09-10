"""Synthetic DCB tests; never opens COM7."""

from unittest.mock import Mock

import pytest

from lms200 import windows_serial_state as ws


def correct_dcb():
    return {
        "BaudRate": 9600,
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
        "DtrControl_symbol": "DTR_CONTROL_DISABLE",
        "RtsControl_symbol": "RTS_CONTROL_DISABLE",
    }


@pytest.mark.parametrize(
    "key,value",
    [
        ("BaudRate", 19200),
        ("ByteSize", 7),
        ("Parity_symbol", "EVENPARITY"),
        ("StopBits_symbol", "ONE5STOPBITS"),
        ("StopBits_symbol", "TWOSTOPBITS"),
        ("fParity", 1),
        ("fOutxCtsFlow", 1),
        ("fOutxDsrFlow", 1),
        ("fDsrSensitivity", 1),
        ("fOutX", 1),
        ("fInX", 1),
        ("DtrControl_symbol", "DTR_CONTROL_HANDSHAKE"),
        ("RtsControl_symbol", "RTS_CONTROL_HANDSHAKE"),
    ],
)
def test_mismatch_blocks_even_when_pyserial_requests_correct_settings(monkeypatch, key, value):
    actual = correct_dcb() | {key: value}
    monkeypatch.setattr(ws.os, "name", "nt")
    monkeypatch.setattr(ws, "read_windows_dcb", lambda device: actual)
    device = Mock(dtr=False, rts=False)
    device.get_settings.return_value = {
        "baudrate": 9600,
        "bytesize": 8,
        "parity": "N",
        "stopbits": 1,
    }
    emit = Mock()
    with pytest.raises(OSError, match="DCB differs"):
        ws.verify_windows_serial(device, 9600, "pre_tx", emit)
    assert emit.call_args.kwargs["confirmed"] is False
    assert key in emit.call_args.kwargs["mismatches"]
    device.write.assert_not_called()


def test_static_control_lines_are_not_handshaking():
    actual = correct_dcb() | {
        "DtrControl_symbol": "DTR_CONTROL_ENABLE",
        "RtsControl_symbol": "RTS_CONTROL_ENABLE",
    }
    assert ws.mismatches(actual, 9600) == {}


@pytest.mark.skipif(ws.os.name != "nt", reason="Windows ctypes constants")
def test_getcommstate_uses_existing_handle_and_symbolic_stopbit(monkeypatch):
    from serial import win32

    observed = []

    def get_state(handle, pointer):
        observed.append(handle)
        dcb = pointer._obj
        assert dcb.DCBlength > 0
        dcb.BaudRate, dcb.ByteSize = 9600, 8
        dcb.Parity, dcb.StopBits = win32.NOPARITY, win32.ONESTOPBIT
        dcb.fBinary = 1
        return True

    monkeypatch.setattr(win32, "GetCommState", get_state)
    device = Mock(is_open=True, _port_handle=12345)
    result = ws.read_windows_dcb(device)
    assert observed == [12345]
    assert result["StopBits"] == win32.ONESTOPBIT == 0
    assert result["StopBits_symbol"] == "ONESTOPBIT" and result["stop_bit_count"] == 1
    assert result["Parity"] == win32.NOPARITY and result["Parity_symbol"] == "NOPARITY"
    device.open.assert_not_called()


@pytest.mark.skipif(ws.os.name != "nt", reason="Windows error details")
def test_failed_getcommstate_preserves_winerror(monkeypatch):
    from serial import win32

    monkeypatch.setattr(win32, "GetCommState", lambda *args: False)
    monkeypatch.setattr(win32, "GetLastError", lambda: 5)
    device = Mock(is_open=True, _port_handle=12345, dtr=False, rts=False)
    device.get_settings.return_value = {}
    emit = Mock()
    with pytest.raises(OSError) as error:
        ws.verify_windows_serial(device, 9600, "pre_tx", emit)
    assert error.value.winerror == 5
    assert emit.call_args.kwargs["error"]["winerror"] == 5
    assert emit.call_args.kwargs["confirmed"] is False
