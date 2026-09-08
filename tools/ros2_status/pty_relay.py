"""WSL-only anonymous-pipe/PTY relay. It never opens physical serial or sends commands.

The ROS node owns the PTY slave; the Windows parent owns COM7. Protocol messages
on stdin/stdout are JSON lines, with serial bytes represented as hex in transit.
"""

import argparse
import errno
import json
import os
import selectors
import subprocess
import sys
import time
import tty
from pathlib import Path


def emit(event, **fields):
    print(json.dumps({"event": event, **fields}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve(strict=True)
    repo = Path(__file__).resolve().parents[2]
    master, slave = os.openpty()
    tty.setraw(slave, when=0)  # TCSANOW; never flush queued bytes.
    os.set_blocking(master, False)
    selector = selectors.DefaultSelector()
    selector.register(master, selectors.EVENT_READ, "pty")
    selector.register(sys.stdin.fileno(), selectors.EVENT_READ, "parent")
    os.set_blocking(sys.stdin.fileno(), False)
    incoming = bytearray()
    pending = bytearray()
    process = None
    try:
        with (run_dir / "ros2-console.log").open("x") as output:
            process = subprocess.Popen(
                [
                    "bash",
                    str(repo / "tools/ros2_status/run-node.sh"),
                    "--port",
                    os.ttyname(slave),
                    "--run-dir",
                    str(run_dir),
                ],
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
            )
            emit("relay_ready", pty=os.ttyname(slave), node_pid=process.pid)
            deadline = time.monotonic() + 665
            while time.monotonic() < deadline:
                if (run_dir / "cancel.trigger").exists():
                    break
                for key, _ in selector.select(0.025):
                    if key.data == "pty":
                        try:
                            data = os.read(master, 4096)
                        except OSError as exc:
                            if exc.errno == errno.EIO:
                                data = b""
                            else:
                                raise
                        if data:
                            emit("node_tx", hex=data.hex().upper(), count=len(data))
                    else:
                        data = os.read(sys.stdin.fileno(), 65536)
                        if not data:
                            return 2
                        incoming.extend(data)
                        if len(incoming) > 131072:
                            raise ValueError("Oversized parent message")
                        while b"\n" in incoming:
                            line, _, remaining = incoming.partition(b"\n")
                            incoming[:] = remaining
                            message = json.loads(line)
                            if message.get("event") != "serial_rx":
                                raise ValueError("Unexpected parent event")
                            pending.extend(bytes.fromhex(message["hex"]))
                if pending:
                    try:
                        count = os.write(master, pending)
                        del pending[:count]
                    except BlockingIOError:
                        pass
                    if len(pending) > 1048576:
                        raise ValueError("PTY receive backlog exceeded limit")
                if process.poll() is not None:
                    # Drain any final node write before reporting exit.
                    try:
                        data = os.read(master, 4096)
                        if data:
                            emit("node_tx", hex=data.hex().upper(), count=len(data))
                    except BlockingIOError:
                        pass
                    emit("node_exit", returncode=process.returncode)
                    return process.returncode
            emit("relay_cancelled_or_deadline")
            return 2
    except Exception as exc:
        emit("relay_error", error=repr(exc))
        return 3
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        selector.close()
        os.close(master)
        os.close(slave)


if __name__ == "__main__":
    raise SystemExit(main())
