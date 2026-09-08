import asyncio
import json

import pytest

from lms200.config import Settings
from lms200.exports import export_scan
from lms200.recording import Recorder
from lms200.service import Service
from lms200.state_machine import Device, State
from lms200.transports.simulator import SimulatorTransport


async def test_record_replay_and_exports(tmp_path):
    service = Service(Settings(recording_dir=tmp_path), SimulatorTransport(realtime=False))
    await service.device.initialize()
    name = await service.start_recording()
    async with asyncio.timeout(3):
        while service.recorder.count < 4:
            await asyncio.sleep(0.02)
    await service.close()
    raw = tmp_path / (name + ".bin")
    decoded = [
        json.loads(line)["scan"] for line in raw.with_suffix(".jsonl").read_text().splitlines()
    ]
    assert bytes.fromhex("".join(d["raw_telegram_hex"] for d in decoded)) == raw.read_bytes()
    received = []
    replay = Device(
        Settings(transport="replay", replay_path=raw, replay_speed=100), on_scan=received.append
    )
    await replay.initialize()
    async with asyncio.timeout(3):
        while replay.state == State.STREAMING:
            await asyncio.sleep(0.01)
    await replay.close()
    assert len(received) == len(decoded)
    assert received[0].timestamp == decoded[0]["timestamp"]
    assert received[0].raw_telegram_hex == decoded[0]["raw_telegram_hex"]
    for kind in ("json", "csv", "pcd"):
        data, mime = export_scan(received[0], kind, service.device.metadata())
        assert "metadata" in data and mime
    pcd, _ = export_scan(received[0], "pcd", {})
    assert "POINTS 181" in pcd and "DATA ascii" in pcd


async def test_slow_subscriber_is_bounded():
    service = Service(Settings(), SimulatorTransport(realtime=False))
    queue = service.subscribe()
    await service.device.initialize()
    await asyncio.sleep(0.15)
    assert queue.qsize() == 2 and service.client_drops > 0
    await service.close()


async def test_recording_can_stop_before_worker_starts(tmp_path):
    service = Service(Settings(recording_dir=tmp_path), SimulatorTransport(realtime=False))
    await service.device.initialize()
    try:
        name = await service.start_recording()
        recorder = service.recorder
        await service.stop_recording()
        assert recorder.closed
        assert service.snapshot()["recording"] is None
        assert (tmp_path / (name + ".bin")).read_bytes() == b""
    finally:
        await service.close()


async def test_recording_can_restart_after_write_failure(tmp_path, monkeypatch):
    service = Service(Settings(recording_dir=tmp_path), SimulatorTransport(realtime=False))
    await service.device.initialize()
    try:
        await service.start_recording()
        failed = service.recorder

        def full_disk(scan):
            raise OSError("Disk full")

        monkeypatch.setattr(failed, "write", full_disk)
        async with asyncio.timeout(3):
            await service._record_task
        assert failed.closed and service.recorder is None and service.record_drops > 0
        await service.start_recording()
        replacement = service.recorder
        async with asyncio.timeout(3):
            while replacement.count == 0:
                await asyncio.sleep(0.01)
        await service.stop_recording()
        assert replacement.closed and replacement.count > 0
    finally:
        await service.close()


@pytest.mark.parametrize("damage", ["raw_tail", "indexed_tail", "short_index", "long_index"])
async def test_corrupt_recording_does_not_report_success(tmp_path, damage):
    device = Device(Settings(), SimulatorTransport(realtime=False))
    await device.initialize()
    try:
        async with asyncio.timeout(3):
            while device.latest is None:
                await asyncio.sleep(0.01)
        recorder = Recorder(tmp_path, device.metadata())
        recorder.write(device.latest)
        recorder.close()
    finally:
        await device.close()
    raw, index = recorder.path, recorder.path.with_suffix(".index.jsonl")
    if damage in ("raw_tail", "indexed_tail"):
        raw.write_bytes(raw.read_bytes()[:-1])
        if damage == "raw_tail":
            index.unlink()
    elif damage == "short_index":
        index.write_text("", encoding="utf-8")
    else:
        entry = json.loads(index.read_text())
        entry["offset"] = raw.stat().st_size
        with index.open("a", encoding="utf-8") as output:
            output.write(json.dumps(entry) + "\n")
    replay = Device(Settings(transport="replay", replay_path=raw, replay_speed=100))
    try:
        await replay.initialize()
        async with asyncio.timeout(3):
            while replay.state == State.STREAMING:
                await asyncio.sleep(0.01)
        assert replay.state == State.FAULTED and replay.error
        assert "Replay complete" not in replay.log
        if damage == "raw_tail":
            assert replay.framer.stats.truncated_frames == 1
    finally:
        await replay.close()
