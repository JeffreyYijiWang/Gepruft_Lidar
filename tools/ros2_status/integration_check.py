"""Offline WSL PTY integration: real ROS2/LaViRIA executable, synthetic scanner bytes."""

import json
import queue
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
from lms200.protocol.framing import encode  # noqa: E402

STARTUP = bytes.fromhex(
    "02 81 17 00 90 4C 4D 53 32 30 30 3B 33 30 31 30 36 33 3B 56 30 32 2E 30 36 20 13 64 5A"
)  # SICK Quick Manual p9, published vector.


def check(address):
    run_dir = Path(tempfile.mkdtemp(prefix=f"ros2-pty-offline-{address:02x}-", dir=REPO / "tmp"))
    child = subprocess.Popen(
        [sys.executable, str(REPO / "tools/ros2_status/pty_relay.py"), "--run-dir", str(run_dir)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    events = queue.Queue()

    def consume():
        for line in child.stdout:
            events.put(json.loads(line))

    thread = threading.Thread(target=consume, daemon=True)
    thread.start()

    def feed(data):
        child.stdin.write(json.dumps({"event": "serial_rx", "hex": data.hex()}) + "\n")
        child.stdin.flush()

    try:
        deadline = time.monotonic() + 20
        while not (run_dir / "ros2.ready").exists():
            if child.poll() is not None or time.monotonic() > deadline:
                raise AssertionError(f"ROS2 listener not ready; inspect {run_dir}")
            time.sleep(0.02)
        feed(STARTUP[:3])
        time.sleep(0.6)
        feed(STARTUP[3:])
        seen = []
        while not events.empty():
            event = events.get_nowait()
            assert event["event"] != "node_tx", "Node wrote before status trigger"
            seen.append(event)
        (run_dir / "status.trigger").write_text("OFFLINE SYNTHETIC TEST\n")
        packet = bytearray()
        while len(packet) < 7:
            event = events.get(timeout=10)
            if event["event"] == "node_tx":
                packet.extend(bytes.fromhex(event["hex"]))
            elif event["event"] in ("relay_error", "node_exit"):
                raise AssertionError(event)
        assert packet == bytes.fromhex("02 00 01 00 31 15 12")
        # Synthetic B1 payload: supported length, embedded control bytes, independent
        # project encoder supplies CRC for comparison with LaViRIA's CRC implementation.
        data = bytearray(146 if address == 0x80 else 152)
        data[:7] = b"V02.10 "
        data[30:34] = bytes.fromhex("06 15 11 13")
        reply = encode(b"\xb1" + data + b"\x10", address)
        feed(b"\x06" + reply[:3])
        time.sleep(0.6)
        feed(reply[3:70])
        feed(reply[70:])
        returncode = child.wait(timeout=12)
        thread.join(timeout=1)
        assert returncode == 0, f"ROS2 failed synthetic exchange: {run_dir}"
        while not events.empty():
            event = events.get_nowait()
            assert event["event"] != "node_tx", "Node retried the status request"
        records = [
            json.loads(line) for line in (run_dir / "ros2-events.jsonl").read_text().splitlines()
        ]
        assert records, "No ROS2 raw/parser evidence"
        assert sum(row["event"] == "library_tx_completed" for row in records) == 1
        final = records[-1]
        assert final["event"] == "result" and final["success"]
        assert final["post_send_seconds"] >= 6
        raw = b"".join(bytes.fromhex(row["hex"]) for row in records if row["event"] == "rx_raw")
        assert raw == STARTUP + b"\x06" + reply
        return {"address": f"{address:02X}", "passed": True, "evidence": str(run_dir)}
    finally:
        if child.poll() is None:
            (run_dir / "cancel.trigger").touch()
            try:
                child.wait(timeout=4)
            except subprocess.TimeoutExpired:
                child.terminate()
                child.wait(timeout=3)
        for pipe in (child.stdin, child.stdout, child.stderr):
            pipe.close()


if __name__ == "__main__":
    print(json.dumps({"offline_only": True, "cases": [check(0x80), check(0x81)]}, indent=2))
