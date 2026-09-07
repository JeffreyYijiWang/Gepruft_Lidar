import asyncio
import json

from lms200.config import Settings
from lms200.exports import export_scan
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
