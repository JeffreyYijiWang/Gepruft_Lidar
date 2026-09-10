"""Offline integrity/timing audit of an address-discovery run. Never opens serial."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path


def audit(directory):
    rows = [json.loads(line) for line in (directory / "events.jsonl").read_text().splitlines()]
    result = json.loads((directory / "result.json").read_text())
    raw = (directory / "rx.bin").read_bytes()
    events = [row["event"] for row in rows]
    reads = [row for row in rows if row["event"] == "windows_dcb_readback"]
    writes = [row for row in rows if row["event"] == "write_returned"]
    attempts = [row for row in rows if row["event"] == "attempt_finished"]
    rx = [row for row in rows if row["event"] == "rx_raw"]
    heartbeats = [row for row in rows if row["event"] == "listener_heartbeat"]
    ready = next(row for row in rows if row["event"] == "listener_ready")
    stopped = next(row for row in rows if row["event"] == "listener_stopped")
    expected_fields = {
        "BaudRate": 9600,
        "ByteSize": 8,
        "Parity_symbol": "NOPARITY",
        "StopBits_symbol": "ONESTOPBIT",
        "stop_bit_count": 1,
        "fParity": 0,
        "fOutxCtsFlow": 0,
        "fOutxDsrFlow": 0,
        "fDsrSensitivity": 0,
        "fDtrControl": 0,
        "fRtsControl": 0,
        "fOutX": 0,
        "fInX": 0,
    }
    assert result["error"] is None and result["listener_error"] is None
    assert result["port_opened"] and result["port_closed"] and result["listener_stopped"]
    assert result["raw_integrity_confirmed"]
    assert raw == b"".join(bytes.fromhex(row["hex"]) for row in rx)
    assert len(raw) == result["rx_os_bytes"] == result["rx_saved_bytes"] == result["raw_file_bytes"]
    assert hashlib.sha256(raw).hexdigest() == result["raw_sha256"]
    assert (
        events.count("listener_ready")
        == events.count("listener_stopped")
        == events.count("port_closed")
        == 1
    )
    if writes:
        assert events.index("listener_ready") < events.index("tx_intent")
    assert events.index("listener_stopped") < events.index("port_closed")
    assert len(reads) >= len(writes) + 1
    handles = {row["windows_dcb"]["handle_hex"] for row in reads}
    assert handles == {ready["handle_hex"]}
    for row in reads:
        assert row["confirmed"] and row["mismatches"] == {}
        assert all(row["windows_dcb"][key] == value for key, value in expected_fields.items())
    for row in writes:
        packet = bytes.fromhex(row["request_hex"])
        assert row["write_return"] == len(packet) == 7
        assert packet[:5] == bytes([2, row["address"], 1, 0, 0x31])
        # Independent two-byte-register CRC, as in the SICK listing.
        crc, previous = 0, 0
        for value in packet[:-2]:
            carry = crc & 0x8000
            crc = (crc << 1) & 0xFFFF
            if carry:
                crc ^= 0x8005
            crc ^= previous << 8 | value
            previous = value
        assert packet[-2:] == crc.to_bytes(2, "little")
    spacing = [b["tx_started"] - a["tx_started"] for a, b in zip(writes, writes[1:], strict=False)]
    assert all(seconds >= 0.1 for seconds in spacing)
    draines = [row for row in rows if row["event"] == "flush_completed"]
    assert len(draines) == len(writes)
    assert all(row["out_waiting"] == 0 for row in draines)
    if result["all_addresses_silent"]:
        assert len(writes) == len(attempts) == 685 and not raw
        assert Counter(row["address"] for row in writes) == {0: 50, **{a: 5 for a in range(1, 128)}}
        assert all(row["classification"] == "SILENT" for row in attempts)
    if heartbeats:
        assert all(row["serial_is_open"] for row in heartbeats)
        counts = (
            [ready["read_calls"]]
            + [row["read_calls"] for row in heartbeats]
            + [stopped["read_calls"]]
        )
        assert all(b > a for a, b in zip(counts, counts[1:], strict=False))
    fields = {
        "offline_audit_passed": True,
        "serial_opened_by_checker": False,
        "run_start_utc": rows[0]["timestamp_utc"],
        "run_end_utc": rows[-1]["timestamp_utc"],
        "handle": ready["handle_hex"],
        "same_handle_dcb_checks": len(reads),
        "listener_ready_utc": ready["timestamp_utc"],
        "listener_read_calls": stopped["read_calls"],
        "listener_heartbeats": len(heartbeats),
        "listener_seconds": stopped["monotonic_seconds"] - ready["monotonic_seconds"],
        "requests": len(writes),
        "driver_accepted_bytes": sum(row["write_return"] for row in writes),
        "raw_rx_bytes": len(raw),
        "all_addresses_silent": result["all_addresses_silent"],
        "attempts_per_address": result["attempts_per_address"],
        "first_request_hex": writes[0]["request_hex"] if writes else None,
        "last_request_hex": writes[-1]["request_hex"] if writes else None,
        "min_tx_spacing_ms": min(spacing) * 1000 if spacing else None,
        "max_tx_spacing_ms": max(spacing) * 1000 if spacing else None,
        "write_call_ms_range": [
            min(row["write_call_ms"] for row in writes),
            max(row["write_call_ms"] for row in writes),
        ]
        if writes
        else None,
        "post_drain_silent_window_ms_range": [
            min(row["listen_seconds"] for row in attempts if row["classification"] == "SILENT")
            * 1000,
            max(row["listen_seconds"] for row in attempts if row["classification"] == "SILENT")
            * 1000,
        ]
        if any(row["classification"] == "SILENT" for row in attempts)
        else None,
        "port_closed": result["port_closed"],
        "physical_signal_measured": False,
    }
    phase = [
        row for row in rows if row["event"] == "address_finished" and row["address_hex"] == "00"
    ]
    fields["universal_phase_seconds"] = (
        phase[0]["monotonic_seconds"] - writes[0]["tx_started"] if phase and writes else None
    )
    return fields


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit(args.directory)
    encoded = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.open("x", encoding="utf-8").write(encoded)
    print(encoded)
