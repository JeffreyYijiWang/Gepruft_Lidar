"""Application coordination, bounded fan-out, asynchronous recording, and diagnostics."""

import asyncio
from contextlib import suppress
from typing import Any

from .config import Settings
from .protocol.measurements import Scan
from .recording import Recorder
from .state_machine import Device, State
from .transports.base import Transport


class Service:
    def __init__(self, settings: Settings, transport: Transport | None = None) -> None:
        self.settings = settings
        self.subscribers: set[asyncio.Queue[Scan]] = set()
        self.device = Device(settings, transport, self.publish)
        self.client_drops = 0
        self.record_drops = 0
        self.recorder: Recorder | None = None
        self._record_queue: asyncio.Queue[Scan | None] = asyncio.Queue(maxsize=128)
        self._record_task: asyncio.Task[None] | None = None
        self._operation: asyncio.Task[None] | None = None
        self._watcher: asyncio.Task[None] | None = None

    def publish(self, scan: Scan) -> None:
        for queue in self.subscribers:
            if queue.full():
                queue.get_nowait()
                self.client_drops += 1
            queue.put_nowait(scan)
        if self.recorder is not None:
            if self._record_queue.full():
                self.record_drops += 1
            else:
                self._record_queue.put_nowait(scan)

    def subscribe(self) -> asyncio.Queue[Scan]:
        queue: asyncio.Queue[Scan] = asyncio.Queue(maxsize=2)
        self.subscribers.add(queue)
        return queue

    async def launch(self) -> None:
        self._watcher = asyncio.create_task(self._watch())
        if self.settings.autostart:
            self.action("start")

    async def _watch(self) -> None:
        while True:
            await asyncio.sleep(0.25)
            if self.device.state == State.FAULTED and not self.busy:
                await self.stop_recording()
                await self.device.close()
                self.device.state = State.FAULTED

    @property
    def busy(self) -> bool:
        return self._operation is not None and not self._operation.done()

    def action(self, name: str) -> None:
        if self.busy:
            raise ValueError("A device operation is already in progress")
        if name in ("start", "reconnect"):
            self.settings.require_write()
        self._operation = asyncio.create_task(self._run_action(name))

    async def _run_action(self, name: str) -> None:
        try:
            if name == "start":
                await self.device.initialize()
            elif name == "reconnect":
                await self.stop_recording()
                await self.device.reconnect()
            elif name == "stop":
                await self.device.close()
                await self.stop_recording()
            elif name == "probe":
                await self.device.connect()
            else:
                raise ValueError("Unknown action")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Exception messages can include host paths or credential-bearing URLs.
            self.device.error = f"{type(exc).__name__}: operation failed; see troubleshooting guide"
            self.device.note(self.device.error)
            await self.device.close()
            self.device.transition(State.FAULTED)

    async def start_recording(self) -> str:
        if self.device.state != State.STREAMING:
            raise ValueError("Start streaming before recording")
        if self.recorder is not None:
            return self.recorder.name
        self.recorder = Recorder(self.settings.recording_dir, self.device.metadata())
        self._record_queue = asyncio.Queue(maxsize=128)
        self._record_task = asyncio.create_task(self._record())
        self.device.note("Recording started")
        return self.recorder.name

    async def _record(self) -> None:
        recorder = self.recorder
        assert recorder is not None
        try:
            while (scan := await self._record_queue.get()) is not None:
                try:
                    await asyncio.to_thread(recorder.write, scan)
                finally:
                    self._record_queue.task_done()
        except Exception:
            self.device.note("Recording failed; check free space and volume permissions")
            self.record_drops += self._record_queue.qsize() + 1
        finally:
            await asyncio.to_thread(recorder.close)

    async def stop_recording(self) -> None:
        if self.recorder is not None:
            # Detach first so no producer appends after the sentinel.
            self.recorder = None
            if self._record_task is not None and not self._record_task.done():
                await self._record_queue.put(None)
                await self._record_task
            self._record_task = None
            self.device.note("Recording finalized")

    def snapshot(self) -> dict[str, Any]:
        return {
            **self.device.snapshot(),
            "busy": self.busy,
            "client_queue_drops": self.client_drops,
            "record_queue_drops": self.record_drops,
            "recording": self.recorder.name if self.recorder and not self.recorder.closed else None,
        }

    async def close(self) -> None:
        if self._watcher is not None:
            self._watcher.cancel()
            with suppress(asyncio.CancelledError):
                await self._watcher
        if self.busy:
            assert self._operation is not None
            self._operation.cancel()
            with suppress(asyncio.CancelledError):
                await self._operation
        await self.device.close()
        await self.stop_recording()
