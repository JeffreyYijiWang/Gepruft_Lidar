import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

from lms200.config import HardwareConsent, Settings
from lms200.exports import export_scan
from lms200.service import Service
from lms200.state_machine import State
from lms200.transports.base import Transport
from lms200.transports.serial import ports

WEB = Path(__file__).parents[1] / "web"


class ActionRequest(BaseModel):
    action: Literal["start", "stop", "reconnect", "probe"]


class ConsentRequest(BaseModel):
    consent: HardwareConsent
    enable_writes: bool


def create_app(settings: Settings | None = None, transport: Transport | None = None) -> FastAPI:
    settings = settings or Settings()
    service = Service(settings, transport)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await service.launch()
        try:
            yield
        finally:
            await service.close()

    app = FastAPI(title="LMS200 local scanner", version="0.1.0", lifespan=lifespan)
    app.state.service = service
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver", "host.docker.internal"],
    )

    @app.middleware("http")
    async def local_origin(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        origin = request.headers.get("origin")
        if request.method not in ("GET", "HEAD", "OPTIONS") and origin:
            if urlparse(origin).netloc != request.headers.get("host"):
                return JSONResponse({"detail": "Cross-origin control is disabled"}, status_code=403)
        result = await call_next(request)
        result.headers["X-Content-Type-Options"] = "nosniff"
        result.headers["Content-Security-Policy"] = (
            "default-src 'self'; connect-src 'self'; style-src 'self'; script-src 'self'; "
            "img-src 'self' data:; frame-ancestors 'none'"
        )
        return result

    @app.get("/health")
    async def health() -> JSONResponse:
        healthy = service.device.state != State.FAULTED
        return JSONResponse(
            {"ok": healthy, "state": service.device.state}, status_code=200 if healthy else 503
        )

    @app.get("/api/status")
    async def status() -> dict[str, Any]:
        return service.snapshot()

    @app.get("/api/ports")
    async def serial_ports() -> list[dict[str, str | int | None]]:
        return await asyncio.to_thread(ports)

    @app.post("/api/consent")
    async def consent(body: ConsentRequest) -> dict[str, bool]:
        if service.busy or service.device.state not in (
            State.DISCONNECTED,
            State.CONNECTED,
            State.FAULTED,
        ):
            raise HTTPException(409, "Stop streaming before changing hardware consent")
        if body.enable_writes:
            try:
                body.consent.require(service.settings.serial_standard)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        service.settings.consent = body.consent
        service.settings.read_only = not body.enable_writes
        return {"writes_enabled": not service.settings.read_only}

    @app.post("/api/action", status_code=202)
    async def action(body: ActionRequest) -> dict[str, bool]:
        try:
            service.action(body.action)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"accepted": True}

    @app.get("/api/scans/latest")
    async def latest() -> dict[str, Any]:
        if service.device.latest is None:
            raise HTTPException(404, "No scan received")
        return service.device.latest.to_dict()

    @app.get("/api/export/{kind}")
    async def export(kind: Literal["json", "csv", "pcd"]) -> Response:
        if service.device.latest is None:
            raise HTTPException(404, "No scan received")
        data, mime = export_scan(service.device.latest, kind, service.device.metadata())
        filename = f"scan-{service.device.latest.sequence}.{kind}"
        return Response(
            data,
            media_type=mime,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.post("/api/record/start")
    async def record_start() -> dict[str, str]:
        try:
            name = await service.start_recording()
        except (ValueError, OSError) as exc:
            raise HTTPException(409, "Cannot start recording; check stream and volume") from exc
        return {"recording": name}

    @app.post("/api/record/stop")
    async def record_stop() -> dict[str, bool]:
        await service.stop_recording()
        return {"stopped": True}

    @app.get("/api/recordings")
    async def recordings() -> list[dict[str, str | int]]:
        directory = service.settings.recording_dir
        if not directory.exists():
            return []
        allowed = (".bin", ".jsonl", ".json")
        return [
            {"name": p.name, "bytes": p.stat().st_size}
            for p in sorted(directory.iterdir())
            if p.is_file() and not p.is_symlink() and p.suffix in allowed
        ]

    @app.get("/api/recordings/{name}")
    async def recording(name: str) -> FileResponse:
        directory = service.settings.recording_dir.resolve()
        path = (directory / name).resolve()
        if (
            path.parent != directory
            or not path.is_file()
            or path.suffix not in (".bin", ".jsonl", ".json")
        ):
            raise HTTPException(404, "Recording not found")
        return FileResponse(path, filename=path.name)

    @app.websocket("/ws/scans")
    async def scans(socket: WebSocket) -> None:
        origin = socket.headers.get("origin")
        if origin and urlparse(origin).netloc != socket.headers.get("host"):
            await socket.close(code=1008)
            return
        await socket.accept()
        queue = service.subscribe()
        try:
            await socket.send_json({"type": "status", "data": service.snapshot()})
            if service.device.latest is not None:
                await socket.send_json({"type": "scan", "data": service.device.latest.to_dict()})
            while True:
                try:
                    scan = await asyncio.wait_for(queue.get(), 0.5)
                    await asyncio.wait_for(
                        socket.send_json({"type": "scan", "data": scan.to_dict()}), 5
                    )
                except TimeoutError:
                    await asyncio.wait_for(
                        socket.send_json({"type": "status", "data": service.snapshot()}), 5
                    )
        except (WebSocketDisconnect, OSError, RuntimeError, TimeoutError):
            pass
        finally:
            service.subscribers.discard(queue)

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(WEB / "index.html")

    app.mount("/static", StaticFiles(directory=WEB), name="static")
    return app
