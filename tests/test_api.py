import time

from fastapi.testclient import TestClient

from lms200.api.app import create_app
from lms200.config import Settings
from lms200.transports.simulator import SimulatorTransport


def test_dashboard_websocket_record_download_and_shutdown(tmp_path):
    sim = SimulatorTransport(realtime=False)
    app = create_app(Settings(recording_dir=tmp_path), sim)
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        assert "Scan station" in client.get("/").text
        assert client.get("/static/app.js").status_code == 200
        assert client.get("/health").json()["ok"]
        assert client.post("/api/action", json={"action": "start"}).status_code == 202
        with client.websocket_connect("/ws/scans") as socket:
            for _ in range(30):
                message = socket.receive_json()
                if message["type"] == "scan":
                    assert message["data"]["count"] == 181
                    break
            else:
                raise AssertionError("No scan on WebSocket")
        assert client.post("/api/record/start").status_code == 200
        time.sleep(0.15)
        assert client.post("/api/record/stop").status_code == 200
        files = client.get("/api/recordings").json()
        assert any(f["name"].endswith(".bin") and f["bytes"] > 0 for f in files)
        for f in files:
            assert client.get("/api/recordings/" + f["name"]).status_code == 200
        for kind in ("json", "csv", "pcd"):
            result = client.get("/api/export/" + kind)
            assert result.status_code == 200 and "metadata" in result.text
        assert client.get("/api/scans/latest").json()["count"] == 181
    assert sim.commands[-1] == b"\x20\x25"


def test_api_safety_origin_and_secret_redaction(tmp_path):
    app = create_app(
        Settings(
            transport="serial",
            serial_port="mock",
            token="DO_NOT_EXPOSE",
            password="12345678",
            recording_dir=tmp_path,
        ),
        SimulatorTransport(),
    )
    with TestClient(app) as client:
        assert client.post("/api/action", json={"action": "start"}).status_code == 409
        assert "DO_NOT_EXPOSE" not in client.get("/api/status").text
        assert "12345678" not in client.get("/api/status").text
        assert (
            client.post(
                "/api/action",
                json={"action": "probe"},
                headers={"Origin": "https://untrusted.example"},
            ).status_code
            == 403
        )
        assert client.get("/health", headers={"Host": "untrusted.example"}).status_code == 400
        assert client.get("/api/recordings/%2e%2e%2fREADME.md").status_code == 404
        assert (
            client.post("/api/consent", json={"enable_writes": True, "consent": {}}).status_code
            == 422
        )
