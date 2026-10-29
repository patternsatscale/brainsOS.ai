from unittest.mock import patch

import pytest
from brainsos_telemetry.system import (
    JobManager,
    create_system_api_app,
    get_system_status,
    issue_csrf_token,
    validate_csrf_token,
)
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def setup_test_env(monkeypatch):
    """Set up test environment with a consistent SYSTEM_API_TOKEN."""
    monkeypatch.setenv("SYSTEM_API_TOKEN", "test-secret-token-12345")
    monkeypatch.setenv("BRAINSOS_DOMAIN", "localhost")
    monkeypatch.setenv("BRAINSOS_STAGE", "test")


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


def test_missing_internal_header_returns_401(monkeypatch):
    monkeypatch.delenv("BRAINSOS_STAGE", raising=False)
    app = create_system_api_app()
    client = TestClient(app)

    # Missing X-BrainsOS-Internal header
    res = client.get("/api/v1/system/status")
    assert res.status_code == 401
    assert "Unauthorized" in res.json().get("detail", "")

    # Invalid X-BrainsOS-Internal header
    res = client.get("/api/v1/system/status", headers={"X-BrainsOS-Internal": "wrong-token"})
    assert res.status_code == 401


def test_valid_internal_header_allows_access():
    app = create_system_api_app()
    client = TestClient(app)

    headers = {"X-BrainsOS-Internal": "test-secret-token-12345"}
    res = client.get("/api/v1/system/status", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data.get("platform") == "brainsOS"


def test_csrf_token_lifecycle():
    token = issue_csrf_token()
    assert isinstance(token, str) and len(token) > 10
    assert validate_csrf_token(token) is True
    assert validate_csrf_token("invalid-token") is False
    assert validate_csrf_token(None) is False


def test_get_csrf_endpoint():
    app = create_system_api_app()
    client = TestClient(app)

    headers = {"X-BrainsOS-Internal": "test-secret-token-12345"}
    res = client.get("/api/v1/system/csrf", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert "csrf_token" in data
    assert validate_csrf_token(data["csrf_token"]) is True
    assert "brainsos_csrf_token" in res.cookies


def test_missing_csrf_returns_403():
    app = create_system_api_app()
    client = TestClient(app)

    headers = {
        "X-BrainsOS-Internal": "test-secret-token-12345",
        "X-Authentik-Username": "operator",
    }
    # POST without CSRF token
    res = client.post("/api/v1/system/update", json={"service": "litellm"}, headers=headers)
    assert res.status_code == 403
    assert "CSRF" in res.json().get("detail", "")


def test_missing_authentik_identity_returns_403():
    app = create_system_api_app()
    client = TestClient(app)

    csrf_tok = issue_csrf_token()
    headers = {
        "X-BrainsOS-Internal": "test-secret-token-12345",
        "X-CSRF-Token": csrf_tok,
    }
    # Missing X-Authentik-Username
    res = client.post("/api/v1/system/update", json={"service": "litellm"}, headers=headers)
    assert res.status_code == 403
    assert "identity" in res.json().get("detail", "").lower()


def test_evil_origin_rejected_with_403():
    app = create_system_api_app()
    client = TestClient(app)

    csrf_tok = issue_csrf_token()
    headers = {
        "X-BrainsOS-Internal": "test-secret-token-12345",
        "X-Authentik-Username": "operator",
        "X-CSRF-Token": csrf_tok,
        "Origin": "https://evil.example.com",
    }
    res = client.post("/api/v1/system/update", json={"service": "litellm"}, headers=headers)
    assert res.status_code == 403
    assert "Origin" in res.json().get("detail", "")


def test_invalid_service_name_rejected_with_400():
    app = create_system_api_app()
    client = TestClient(app)

    csrf_tok = issue_csrf_token()
    headers = {
        "X-BrainsOS-Internal": "test-secret-token-12345",
        "X-Authentik-Username": "operator",
        "X-CSRF-Token": csrf_tok,
        "Origin": "http://localhost",
    }
    res = client.post(
        "/api/v1/system/update",
        json={"service": "unknown_hacked_service"},
        headers=headers,
    )
    assert res.status_code == 400
    assert "Invalid service" in res.json().get("detail", "")


@pytest.mark.asyncio
async def test_single_flight_lock_returns_409(tmp_path):
    manager = JobManager(str(tmp_path))

    # Start a slow background sleep job
    job1 = await manager.start_job("update", ["sleep", "5"])
    assert "id" in job1
    assert job1["status"] == "running"

    # Attempt to start a concurrent job
    job2 = await manager.start_job("prune", ["sleep", "1"])
    assert job2.get("error") == "conflict"
    assert job2.get("active_job_id") == job1["id"]

    # Cancel the running sleep task
    if "task" in job1 and job1["task"]:
        job1["task"].cancel()


@pytest.mark.asyncio
async def test_detached_job_runs_to_completion_and_writes_log(tmp_path):
    manager = JobManager(str(tmp_path))

    job = await manager.start_job("test", ["echo", "brainsos-detached-success"])
    task = job.get("task")
    assert task is not None
    await task

    # Verify job record and log output
    fetched = manager.get_job(job["id"])
    assert fetched is not None
    assert fetched["status"] == "success"
    assert fetched["exit_code"] == 0
    assert any("brainsos-detached-success" in line for line in fetched.get("logs", []))


@pytest.mark.asyncio
async def test_disconnect_mid_stream_lets_job_finish(tmp_path):
    manager = JobManager(str(tmp_path))

    # Job prints line 1, sleeps 0.2s, prints line 2
    cmd = ["bash", "-c", "echo line1 && sleep 0.2 && echo line2"]
    job = await manager.start_job("test", cmd)

    from brainsos_telemetry.system import stream_job_logs

    # Simulate client reading just the first event then disconnecting
    gen = stream_job_logs(job)
    first_event = await gen.__anext__()
    assert "job_id" in first_event

    # Client closes generator (disconnects)
    await gen.aclose()

    # The detached task must still be running and finish
    task = job.get("task")
    assert task is not None
    await task

    fetched = manager.get_job(job["id"])
    assert fetched["status"] == "success"
    logs = fetched.get("logs", [])
    assert any("line1" in item for item in logs)
    assert any("line2" in item for item in logs)


def test_get_job_endpoint(tmp_path):
    with patch("brainsos_telemetry.system.get_repo_root", return_value=str(tmp_path)):
        app = create_system_api_app()
        client = TestClient(app)

        headers = {"X-BrainsOS-Internal": "test-secret-token-12345"}
        res = client.get("/api/v1/system/jobs/nonexistent-id", headers=headers)
        assert res.status_code == 404
