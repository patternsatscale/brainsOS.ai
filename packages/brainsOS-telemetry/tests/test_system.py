import json

import pytest
from brainsos_telemetry.system import (
    create_system_api_app,
    get_system_status,
    stream_system_update,
)
from fastapi.testclient import TestClient


def test_get_system_status_schema():
    status = get_system_status()
    assert isinstance(status, dict)
    assert status.get("platform") == "brainsOS"
    assert "git" in status
    assert "services" in status
    assert "disk" in status
    assert "overall_update_available" in status
    assert isinstance(status["git"], dict)
    assert isinstance(status["services"], dict)
    assert isinstance(status["disk"], dict)
    assert "total_gb" in status["disk"]
    assert "free_gb" in status["disk"]
    assert "free_pct" in status["disk"]
    assert "warning" in status["disk"]


def test_system_api_health_endpoint():
    app = create_system_api_app()
    client = TestClient(app)

    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data.get("status") == "healthy"
    assert data.get("service") == "brainsos-telemetry-system"

    api_response = client.get("/api/v1/system/health")
    assert api_response.status_code == 200


def test_system_api_status_endpoint():
    app = create_system_api_app()
    client = TestClient(app)

    response = client.get("/api/v1/system/status")
    assert response.status_code == 200
    data = response.json()
    assert data.get("platform") == "brainsOS"
    assert "git" in data
    assert "services" in data
    assert "disk" in data


@pytest.mark.asyncio
async def test_stream_system_update_start_event():
    # Test generator emits start event
    events = []
    async for chunk in stream_system_update(service="litellm"):
        events.append(chunk)
        if len(events) >= 2:
            break

    assert len(events) >= 1
    assert events[0].startswith("data: ")
    payload = json.loads(events[0][6:].strip())
    assert payload.get("type") in ("start", "error")


@pytest.mark.asyncio
async def test_stream_prune_logs_start_event():
    from brainsos_telemetry.system import stream_prune_logs

    events = []
    async for chunk in stream_prune_logs(check=True):
        events.append(chunk)
        if len(events) >= 2:
            break

    assert len(events) >= 1
    assert events[0].startswith("data: ")
    payload = json.loads(events[0][6:].strip())
    assert payload.get("type") in ("start", "error", "log")


def test_system_api_prune_endpoint():
    app = create_system_api_app()
    client = TestClient(app)

    response = client.post("/api/v1/system/prune-logs", json={"dry_run": True})
    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")

