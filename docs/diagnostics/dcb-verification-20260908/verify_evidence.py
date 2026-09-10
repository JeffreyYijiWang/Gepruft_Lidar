"""Offline consistency check of this audit's saved records; never opens serial."""

import hashlib
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
PACKET = "02 00 01 00 31 15 12"


def records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def check_dcb(value):
    expected = {
        "BaudRate": 9600,
        "ByteSize": 8,
        "Parity": 0,
        "Parity_symbol": "NOPARITY",
        "StopBits": 0,
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
        "fNull": 0,
        "fErrorChar": 0,
        "fAbortOnError": 0,
    }
    for key, required in expected.items():
        assert value[key] == required, (key, value[key], required)


def check_python(path):
    rows = records(path)
    reads = [row for row in rows if row["event"] == "windows_dcb_readback"]
    assert len(reads) == 2
    assert [row["stage"] for row in reads] == ["after_configuration", "immediately_before_write"]
    for row in reads:
        assert row["confirmed"] and row["api"] == "GetCommState"
        assert row["mismatches"] == {}
        check_dcb(row["windows_dcb"])
    assert reads[0]["windows_dcb"]["handle_hex"] == reads[1]["windows_dcb"]["handle_hex"]
    tx = [row for row in rows if row["event"] == "tx_attempt"]
    assert len(tx) == 1 and tx[0]["count"] == 7 and tx[0]["hex"] == PACKET
    assert rows.index(reads[1]) < rows.index(tx[0])
    writes = [row for row in rows if row["event"] == "write_returned"]
    assert len(writes) == 1 and writes[0]["count"] == 7
    drain = [row for row in rows if row["event"] == "flush_completed"]
    assert len(drain) == 1 and drain[0]["out_waiting"] == 0
    final = rows[-1]
    assert final["event"] == "result" and final["port_closed"]
    assert final["rx_bytes"] == 0 and final["rx_hex"] == ""
    assert not final["ack"] and not final["nak"] and final["telegrams"] == []
    assert final.get("exception") is None and final.get("error") is None
    return rows[0]["timestamp"], final["timestamp"]


python_interval = check_python(ROOT / "python.jsonl")
ros2_interval = check_python(ROOT / "ros2/windows-raw.jsonl")
native_rows = records(ROOT / "native/events.jsonl")
native = [row["detail"] for row in native_rows]
reads = [row for row in native if row["event"] == "windows_dcb_readback"]
assert len(reads) == 2 and reads[0]["handle"] == reads[1]["handle"]
assert [row["stage"] for row in reads] == ["after_configuration", "immediately_before_WriteFile"]
for row in reads:
    assert row["confirmed"] and row["api"] == "GetCommState"
    check_dcb(row)
tx = [row for row in native if row["event"] == "tx_intent"]
assert len(tx) == 1 and tx[0]["count"] == 7 and tx[0]["hex"] == PACKET
writes = [row for row in native if row["event"] == "write_result"]
assert len(writes) == 1 and writes[0]["os_reported_count"] == 7
assert writes[0]["complete"] and writes[0]["win32_error"] == 0
assert native.index(reads[1]) < native.index(writes[0])
drain = [row for row in native if row["event"] == "output_drain_complete"]
assert len(drain) == 1 and drain[0]["os_output_queue"] == 0
result = json.loads((ROOT / "native/result.json").read_text())
assert result["port_closed"] and result["reader_healthy_at_close"]
assert result["run_mode"] == "single_status" and not result["start_attempted"]
assert not result["stop_attempted"] and not result["variant_requested"]
assert result["evidence"]["raw_rx_bytes"] == 0
assert datetime.fromisoformat(python_interval[1]) < datetime.fromisoformat(native_rows[0]["utc"])
assert datetime.fromisoformat(result["utc"]) < datetime.fromisoformat(ros2_interval[0])

for raw in (ROOT / "python.rx.bin", ROOT / "native/rx.bin"):
    assert raw.stat().st_size == 0
manifest = json.loads((ROOT / "native/build-manifest.json").read_text())
for source in manifest["sources"]:
    path = REPO / "tools/lms200_native" / source["file"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == source["sha256"].lower()
assert (
    hashlib.sha256(Path(manifest["executable"]).read_bytes()).hexdigest()
    == manifest["executableSha256"].lower()
)
manifest = json.loads((ROOT / "ros2/build-evidence.json").read_text())
for name, expected in manifest["files"].items():
    content = (REPO / name).read_bytes()
    assert len(content) == expected["size"]
    assert hashlib.sha256(content).hexdigest() == expected["sha256"]
print(
    json.dumps(
        {
            "offline_saved_evidence_consistent": True,
            "serial_opened_by_this_checker": False,
            "confirmed_programs": [
                "Python hardware diagnostic",
                "native C++",
                "ROS 2 Windows owner",
            ],
            "actual_saved_readbacks_checked": 6,
            "one_status_write_per_program": True,
            "all_handles_closed_before_next_open": True,
            "native_and_ros2_source_artifact_hashes_match": True,
            "total_driver_accepted_bytes": 21,
            "total_received_bytes": 0,
            "scanner_receipt_or_physical_framing_proven": False,
        },
        indent=2,
    )
)
