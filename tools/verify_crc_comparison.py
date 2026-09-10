"""Offline audit of CRC-comparison raw evidence. This script never opens serial."""

import argparse
import hashlib
import json
from pathlib import Path

PACKETS = {"A_valid": "02 00 01 00 31 15 12", "B_reversed_crc": "02 00 01 00 31 12 15"}


def value_range(values):
    return [min(values), max(values)] if values else None


def audit(directory):
    rows = [json.loads(line) for line in (directory / "events.jsonl").read_text().splitlines()]
    result = json.loads((directory / "result.json").read_text())
    raw = (directory / "rx.bin").read_bytes()

    def events(name):
        return [row for row in rows if row["event"] == name]

    assert result["clean_capture_and_close"]
    assert result["error"] is None and result["listener_error"] is None
    assert result["port_opened"] and result["port_closed"] and result["listener_stopped"]
    assert not result.get("close_error") and not result.get("cancel_read_error")
    assert result["raw_integrity_confirmed"]
    assert raw == b"".join(bytes.fromhex(row["hex"]) for row in events("rx_raw"))
    assert len(raw) == result["rx_os_bytes"] == result["rx_saved_bytes"] == result["raw_file_bytes"]
    assert hashlib.sha256(raw).hexdigest() == result["raw_sha256"]
    assert len(events("listener_ready")) == len(events("listener_stopped")) == 1
    assert len(events("port_closed")) == len(events("run_started")) == 1
    ready, stopped = events("listener_ready")[0], events("listener_stopped")[0]
    reads, writes = events("windows_dcb_readback"), events("write_returned")
    assert len(reads) >= len(writes) + 1
    assert {r["windows_dcb"]["handle_hex"] for r in reads} == {ready["handle_hex"]}
    expected = {
        "BaudRate": 9600,
        "ByteSize": 8,
        "Parity_symbol": "NOPARITY",
        "StopBits_symbol": "ONESTOPBIT",
        "stop_bit_count": 1,
        "fParity": 0,
        "fBinary": 1,
        "fOutxCtsFlow": 0,
        "fOutxDsrFlow": 0,
        "fDsrSensitivity": 0,
        "fDtrControl": 0,
        "fRtsControl": 0,
        "fOutX": 0,
        "fInX": 0,
    }
    assert reads[0]["stage"] == "after_configuration"
    for row in reads:
        assert row["confirmed"] and row["mismatches"] == {}
        assert all(row["windows_dcb"][key] == value for key, value in expected.items())
    assert len(writes) == len(result["attempts"]) <= 40
    if writes:
        assert ready["monotonic_seconds"] < writes[0]["tx_started"]
        assert stopped["monotonic_seconds"] > writes[-1]["write_completed"]
    assert stopped["read_calls"] > 0
    assert stopped["monotonic_seconds"] < events("port_closed")[0]["monotonic_seconds"]
    for row in writes:
        assert row["address"] == 0 and row["write_return"] == 7
        assert row["request_hex"] == PACKETS[row["test"]]
        assert row["crc_calculated"] == "1215" and row["correct_wire_crc"] == "15 12"
        assert row["crc_intentionally_invalid"] == (row["test"] == "B_reversed_crc")
        assert row["supplied_wire_crc"] == PACKETS[row["test"]][-5:]
        preceding = [
            r
            for r in reads
            if r["stage"] == "immediately_before_write"
            and r["test"] == row["test"]
            and r["attempt"] == row["attempt"]
        ]
        assert len(preceding) == 1 and preceding[0]["monotonic_seconds"] < row["tx_started"]
    # Independent register implementation for the fixed five-byte prefix.
    crc, previous = 0, 0
    for value in bytes.fromhex("02 00 01 00 31"):
        carry = crc & 0x8000
        crc = ((crc << 1) & 0xFFFF) ^ (0x8005 if carry else 0)
        crc ^= previous << 8 | value
        previous = value
    assert crc == 0x1215
    draines = events("flush_completed")
    assert len(draines) == len(writes) and all(r["out_waiting"] == 0 for r in draines)
    spacing = [
        (b["tx_started"] - a["tx_started"]) * 1000 for a, b in zip(writes, writes[1:], strict=False)
    ]
    assert all(ms >= 100 for ms in spacing)
    tests = {}
    for name in PACKETS:
        selected = [r for r in result["attempts"] if r["test"] == name]
        assert [r["attempt"] for r in selected] == list(range(1, len(selected) + 1))
        assert len(selected) == result["tests"][name]["attempts"] <= 20
        tests[name] = {
            **result["tests"][name],
            "driver_accepted_bytes": sum(r["write_return"] for r in selected),
            "write_call_ms_range": value_range([r["write_call_ms"] for r in selected]),
            "drain_call_ms_range": value_range([r["drain_call_ms"] for r in selected]),
            "post_drain_silent_window_ms_range": value_range(
                [r["listen_seconds"] * 1000 for r in selected if r["classification"] == "SILENT"]
            ),
        }
    b_writes = [r for r in writes if r["test"] == "B_reversed_crc"]
    if b_writes:
        baseline = [r for r in events("attempt_finished") if r["test"] == "A_valid"]
        assert len(baseline) == 20 and all(r["classification"] == "SILENT" for r in baseline)
        assert baseline[-1]["monotonic_seconds"] < b_writes[0]["tx_started"]
        assert [r["test"] for r in writes] == ["A_valid"] * 20 + ["B_reversed_crc"] * len(b_writes)
    if result["both_crc_tests_silent"]:
        assert len(writes) == 40 and not raw
        assert all(r["classification"] == "SILENT" for r in result["attempts"])
    assert result["electrical_measurement"]["measured"] is False
    return {
        "offline_audit_passed": True,
        "serial_opened_by_checker": False,
        "run_start_utc": rows[0]["timestamp_utc"],
        "run_end_utc": rows[-1]["timestamp_utc"],
        "pid": ready["pid"],
        "handle": ready["handle_hex"],
        "same_handle_dcb_checks": len(reads),
        "listener_ready_utc": ready["timestamp_utc"],
        "listener_read_calls": stopped["read_calls"],
        "listener_heartbeats": len(events("listener_heartbeat")),
        "listener_seconds": stopped["monotonic_seconds"] - ready["monotonic_seconds"],
        "requests": len(writes),
        "driver_accepted_bytes": sum(r["write_return"] for r in writes),
        "raw_rx_bytes": len(raw),
        "both_crc_tests_silent": result["both_crc_tests_silent"],
        "tx_spacing_ms_range": value_range(spacing),
        "tests": tests,
        "port_closed": result["port_closed"],
        "electrical_measurement": result["electrical_measurement"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    encoded = json.dumps(audit(args.directory), indent=2) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded)
    print(encoded)
