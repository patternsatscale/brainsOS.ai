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
    assert "platform_name" in status
    assert "platform_detail" in status
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


def test_detect_appliance_platform_aws_ami(tmp_path, monkeypatch):
    from brainsos_telemetry.system import detect_appliance_platform

    (tmp_path / ".brainsos-initialized").write_text("2026-11-05\n", encoding="utf-8")
    monkeypatch.setenv("COMPOSE_FILE", "docker-compose.yml:docker/compose/compose.appliance.yml")
    pname, pdetail = detect_appliance_platform(str(tmp_path))
    assert pname == "AWS EC2 Appliance (AMI)"
    assert "AWS" in pdetail


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


def test_update_passes_version_and_rejects_invalid_version(tmp_path):
    script_dir = tmp_path / "scripts" / "control"
    script_dir.mkdir(parents=True)
    update_sh = script_dir / "update.sh"
    update_sh.write_text("#!/usr/bin/env bash\necho \"ARGS: $*\"\n", encoding="utf-8")
    update_sh.chmod(0o755)

    with patch("brainsos_telemetry.system.get_repo_root", return_value=str(tmp_path)):
        app = create_system_api_app()
        client = TestClient(app)
        csrf_tok = issue_csrf_token()
        headers = {
            "X-BrainsOS-Internal": "test-secret-token-12345",
            "X-Authentik-Username": "operator",
            "X-CSRF-Token": csrf_tok,
            "Origin": "http://localhost",
        }

        # Reject invalid version with leading dash
        bad_res = client.post(
            "/api/v1/system/update",
            json={"service": "litellm", "version": "--evil-flag"},
            headers=headers,
        )
        assert bad_res.status_code == 400

        # Valid version is forwarded to update.sh --version
        ok_res = client.post(
            "/api/v1/system/update",
            json={"service": "litellm", "version": "1.108.0"},
            headers=headers,
        )
        assert ok_res.status_code == 200
        assert "--version 1.108.0" in ok_res.text

        # Reject invalid branch with path traversal or leading dash
        bad_branch = client.post(
            "/api/v1/system/update",
            json={"branch": "../evil"},
            headers=headers,
        )
        assert bad_branch.status_code == 400

        bad_branch_dash = client.post(
            "/api/v1/system/update",
            json={"branch": "--evil-flag"},
            headers=headers,
        )
        assert bad_branch_dash.status_code == 400

        # Valid branch is forwarded to update.sh --branch
        ok_branch = client.post(
            "/api/v1/system/update",
            json={"branch": "task/320-appliance-rehearsal"},
            headers=headers,
        )
        assert ok_branch.status_code == 200
        assert "--branch task/320-appliance-rehearsal" in ok_branch.text


def test_identity_and_firstboot_wizard_status(tmp_path):
    (tmp_path / ".env").write_text(
        "BRAINSOS_URL=ec2-32-192-215-107.compute-1.amazonaws.com\n"
        "BRAINSOS_LOCAL_DOMAIN=jsm.cloud.aws.brainsos.ai\n"
        "BRAINSOS_ADMIN_USERNAME=jsm\n"
        "BRAINSOS_TLS_MODE=internal\n",
        encoding="utf-8",
    )
    (tmp_path / ".brainsos-initialized").write_text("2026-11-06T00:00:00Z\n", encoding="utf-8")

    with patch("brainsos_telemetry.system.get_repo_root", return_value=str(tmp_path)):
        app = create_system_api_app()
        client = TestClient(app)
        headers = {"X-BrainsOS-Internal": "test-secret-token-12345"}

        res = client.get("/api/v1/system/identity", headers=headers)
        assert res.status_code == 200
        ident = res.json()
        assert ident["firstboot_wizard_completed"] is False
        assert ident["url"] == "ec2-32-192-215-107.compute-1.amazonaws.com"
        assert ident["local_domain"] == "jsm.cloud.aws.brainsos.ai"
        assert ident["admin_username"] == "jsm"
        assert ident["admin_email"] == "jsm@jsm.cloud.aws.brainsos.ai"

        # Dismiss wizard via POST /api/v1/system/setup
        csrf_tok = issue_csrf_token()
        post_headers = {
            **headers,
            "X-Authentik-Username": "jsm",
            "X-CSRF-Token": csrf_tok,
            "Origin": "http://localhost",
        }
        dismiss_res = client.post(
            "/api/v1/system/setup",
            json={"dismiss_only": True},
            headers=post_headers,
        )
        assert dismiss_res.status_code == 200
        assert dismiss_res.json()["firstboot_wizard_completed"] is True
        assert (tmp_path / ".brainsos-wizard-completed").is_file()


def test_dns_check_and_setup_password_never_logged(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAINSOS_TEST_PUBLIC_IPV4", "32.192.215.107")
    script_dir = tmp_path / "scripts" / "control"
    script_dir.mkdir(parents=True)
    set_domain_sh = script_dir / "set-domain.sh"
    set_domain_sh.write_text(
        "#!/usr/bin/env bash\n"
        "echo \"SET_DOMAIN_ARGS: $*\"\n"
        "if [ -n \"${BRAINSOS_NEW_ADMIN_PASSWORD:-}\" ]; then echo \"PASS_ENV_RECEIVED=yes\"; fi\n",
        encoding="utf-8",
    )
    set_domain_sh.chmod(0o755)

    with patch("brainsos_telemetry.system.get_repo_root", return_value=str(tmp_path)):
        app = create_system_api_app()
        client = TestClient(app)
        csrf_tok = issue_csrf_token()
        headers = {
            "X-BrainsOS-Internal": "test-secret-token-12345",
            "X-Authentik-Username": "admin",
            "X-CSRF-Token": csrf_tok,
            "Origin": "http://localhost",
        }

        with patch("socket.gethostbyname", return_value="32.192.215.107"):
            dns_res = client.post(
                "/api/v1/system/dns-check",
                json={"domain": "https://portal.brainsos.ai/"},
                headers=headers,
            )
            assert dns_res.status_code == 200
            dns_data = dns_res.json()
            assert dns_data["domain"] == "portal.brainsos.ai"
            assert dns_data["valid_syntax"] is True
            assert dns_data["matches_appliance"] is True

        # Reject invalid local_domain
        bad_setup = client.post(
            "/api/v1/system/setup",
            json={"local_domain": "not_a_fqdn"},
            headers=headers,
        )
        assert bad_setup.status_code == 400

        # Valid setup streams SSE and passes password via env var (never in command args)
        ok_setup = client.post(
            "/api/v1/system/setup",
            json={
                "local_domain": "jsm.cloud.aws.brainsos.ai",
                "admin_username": "jsm",
                "admin_password": "UltraSecretPassword99!",
                "url": "https://ec2-32-192-215-107.compute-1.amazonaws.com/",
                "tls_mode": "internal",
            },
            headers=headers,
        )
        assert ok_setup.status_code == 200
        assert "--local-domain jsm.cloud.aws.brainsos.ai" in ok_setup.text
        assert "--admin-username jsm" in ok_setup.text
        assert "PASS_ENV_RECEIVED=yes" in ok_setup.text
        assert "UltraSecretPassword99!" not in ok_setup.text


def test_prelogin_firstboot_wizard_requires_valid_instance_id_token(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAINSOS_TEST_INSTANCE_ID", "i-0abc123456789def0")
    (tmp_path / ".env").write_text(
        "BRAINSOS_URL=ec2-32-192-215-107.compute-1.amazonaws.com\n"
        "BRAINSOS_LOCAL_DOMAIN=local.brainsos.ai\n"
        "BRAINSOS_ADMIN_USERNAME=admin\n"
        "BRAINSOS_ADMIN_PASSWORD=i-0abc123456789def0\n"
        "BRAINSOS_WIZARD_COMPLETED=false\n",
        encoding="utf-8",
    )
    (tmp_path / ".brainsos-initialized").write_text("2026-11-06T00:00:00Z\n", encoding="utf-8")

    script_dir = tmp_path / "scripts" / "control"
    script_dir.mkdir(parents=True)
    set_domain_sh = script_dir / "set-domain.sh"
    set_domain_sh.write_text("#!/usr/bin/env bash\necho \"PRELOGIN_SETUP_OK: $*\"\n", encoding="utf-8")
    set_domain_sh.chmod(0o755)

    with patch("brainsos_telemetry.system.get_repo_root", return_value=str(tmp_path)):
        app = create_system_api_app()
        client = TestClient(app)
        csrf_tok = issue_csrf_token()
        # No X-Authentik-Username header (pre-sign-in wizard state)
        prelogin_headers = {
            "X-BrainsOS-Internal": "test-secret-token-12345",
            "X-CSRF-Token": csrf_tok,
            "Origin": "http://localhost",
        }

        # 1. GET /api/v1/system/identity masks instance_id before wizard completion
        ident_res = client.get("/api/v1/system/identity", headers=prelogin_headers)
        assert ident_res.status_code == 200
        assert ident_res.json()["firstboot_wizard_completed"] is False
        assert ident_res.json()["instance_id"] == ""

        # 2. Missing or wrong bootstrap_token is rejected with HTTP 403
        bad_token_res = client.post(
            "/api/v1/system/setup",
            json={
                "bootstrap_token": "i-wrongtoken999",
                "local_domain": "jsm.cloud.aws.brainsos.ai",
                "admin_username": "jsm",
                "admin_password": "NewStrongPassword123!",
                "url": "ec2-32-192-215-107.compute-1.amazonaws.com",
                "tls_mode": "internal",
            },
            headers=prelogin_headers,
        )
        assert bad_token_res.status_code == 403
        assert "Instance ID" in bad_token_res.json().get("detail", "")

        # 3. Valid EC2 Instance ID bootstrap_token succeeds pre-login
        ok_token_res = client.post(
            "/api/v1/system/setup",
            json={
                "bootstrap_token": "i-0abc123456789def0",
                "local_domain": "jsm.cloud.aws.brainsos.ai",
                "admin_username": "jsm",
                "admin_password": "NewStrongPassword123!",
                "url": "ec2-32-192-215-107.compute-1.amazonaws.com",
                "tls_mode": "internal",
            },
            headers=prelogin_headers,
        )
        assert ok_token_res.status_code == 200
        assert "PRELOGIN_SETUP_OK:" in ok_token_res.text
        assert "--admin-username jsm" in ok_token_res.text


def test_superuser_setup_and_password_complexity(tmp_path, monkeypatch):
    from brainsos_telemetry.system import validate_password_complexity

    assert validate_password_complexity("short1!") is not None
    assert validate_password_complexity("alllowercase123!") is not None
    assert validate_password_complexity("ALLUPPERCASE123!") is not None
    assert validate_password_complexity("NoDigitsHere!") is not None
    assert validate_password_complexity("NoSpecialChars123") is not None
    assert validate_password_complexity("i-0abc123456789def0", instance_id="i-0abc123456789def0") is not None
    assert validate_password_complexity("ValidSuperPass99!", username="jsm", instance_id="i-0abc123456789def0") is None

    monkeypatch.setenv("BRAINSOS_TEST_INSTANCE_ID", "i-0abc123456789def0")
    (tmp_path / ".env").write_text(
        "BRAINSOS_URL=ec2-32-192-215-107.compute-1.amazonaws.com\n"
        "BRAINSOS_LOCAL_DOMAIN=local.brainsos.ai\n"
        "BRAINSOS_ADMIN_USERNAME=admin\n"
        "BRAINSOS_ADMIN_PASSWORD=i-0abc123456789def0\n"
        "BRAINSOS_INSTANCE_ID=i-0abc123456789def0\n"
        "BRAINSOS_WIZARD_COMPLETED=false\n",
        encoding="utf-8",
    )
    script_dir = tmp_path / "scripts" / "control"
    script_dir.mkdir(parents=True)
    set_domain_sh = script_dir / "set-domain.sh"
    set_domain_sh.write_text("#!/usr/bin/env bash\necho \"SUPERUSER_SETUP_ARGS: $*\"\n", encoding="utf-8")
    set_domain_sh.chmod(0o755)

    with patch("brainsos_telemetry.system.get_repo_root", return_value=str(tmp_path)):
        app = create_system_api_app()
        client = TestClient(app)
        csrf_tok = issue_csrf_token()
        headers = {
            "X-BrainsOS-Internal": "test-secret-token-12345",
            "X-Authentik-Username": "admin",
            "X-CSRF-Token": csrf_tok,
            "Origin": "http://localhost",
        }

        # Reject superuser_username == 'admin'
        admin_res = client.post(
            "/api/v1/system/setup",
            json={
                "superuser_name": "Admin User",
                "superuser_username": "admin",
                "superuser_password": "ValidSuperPass99!",
            },
            headers=headers,
        )
        assert admin_res.status_code == 400
        assert "permanently bound" in admin_res.json().get("detail", "")

        # Reject weak superuser_password
        weak_res = client.post(
            "/api/v1/system/setup",
            json={
                "superuser_name": "Jane Smith",
                "superuser_username": "jsm",
                "superuser_password": "weakpassword",
            },
            headers=headers,
        )
        assert weak_res.status_code == 400

        # Valid named superuser setup auto-suggests jsm.aws.cloud.brainsos.ai when local_domain omitted
        ok_res = client.post(
            "/api/v1/system/setup",
            json={
                "superuser_name": "Jane Smith",
                "superuser_username": "jsm",
                "superuser_password": "ValidSuperPass99!",
            },
            headers=headers,
        )
        assert ok_res.status_code == 200
        assert "--local-domain jsm.aws.cloud.brainsos.ai" in ok_res.text
        assert "--superuser-name Jane Smith" in ok_res.text
        assert "--admin-username jsm" in ok_res.text


def test_runners_status_and_hermes_firecrawl_config(tmp_path):
    (tmp_path / ".env").write_text("BRAINSOS_DATA_DIR=./data\n", encoding="utf-8")

    with patch("brainsos_telemetry.system.get_repo_root", return_value=str(tmp_path)):
        app = create_system_api_app()
        client = TestClient(app)
        csrf_tok = issue_csrf_token()
        headers = {
            "X-BrainsOS-Internal": "test-secret-token-12345",
            "X-Authentik-Username": "jsm",
            "X-CSRF-Token": csrf_tok,
            "Origin": "http://localhost",
        }

        # Initial runners status has firecrawl_configured == False
        r1 = client.get("/api/v1/system/runners", headers=headers)
        assert r1.status_code == 200
        assert r1.json()["hermes"]["firecrawl_configured"] is False

        # Save FIRECRAWL_API_KEY
        raw_key = "fc-9876543210abcdefSECRET"
        r2 = client.post(
            "/api/v1/system/runners/hermes/config",
            json={"firecrawl_api_key": raw_key, "restart_runner": False},
            headers=headers,
        )
        assert r2.status_code == 200
        body = r2.json()
        assert body["status"] == "updated"
        assert body["runners"]["hermes"]["firecrawl_configured"] is True
        masked = body["runners"]["tool_keys"]["FIRECRAWL_API_KEY"]["masked"]
        assert masked.startswith("fc-9")
        assert raw_key not in r2.text


def test_os_telemetry_upgrade_and_reboot_endpoints(tmp_path, monkeypatch):
    updates_file = tmp_path / "updates-available"
    updates_file.write_text(
        "14 updates can be applied immediately.\n9 of these updates are standard security updates.\n",
        encoding="utf-8",
    )
    reboot_file = tmp_path / "reboot-required"
    reboot_file.write_text("*** System restart required ***\n", encoding="utf-8")
    reboot_pkgs = tmp_path / "reboot-required.pkgs"
    reboot_pkgs.write_text("linux-image-aws\nlibc6\n", encoding="utf-8")

    monkeypatch.setenv("BRAINSOS_UPDATES_AVAILABLE_FILE", str(updates_file))
    monkeypatch.setenv("BRAINSOS_REBOOT_REQUIRED_FILE", str(reboot_file))
    monkeypatch.setenv("BRAINSOS_REBOOT_PACKAGES_FILE", str(reboot_pkgs))

    script_dir = tmp_path / "scripts" / "control"
    script_dir.mkdir(parents=True)
    update_sh = script_dir / "update.sh"
    update_sh.write_text("#!/usr/bin/env bash\necho \"OS_UPGRADE_ARGS: $*\"\n", encoding="utf-8")
    update_sh.chmod(0o755)
    reboot_sh = script_dir / "reboot-appliance.sh"
    reboot_sh.write_text("#!/usr/bin/env bash\necho \"REBOOT_ARGS: $*\"\n", encoding="utf-8")
    reboot_sh.chmod(0o755)

    from brainsos_telemetry.system import get_host_os_status

    os_stat = get_host_os_status(str(tmp_path))
    assert os_stat["pending_packages"] == 14
    assert os_stat["security_packages"] == 9
    assert os_stat["reboot_required"] is True
    assert "linux-image-aws" in os_stat["reboot_packages"]

    with patch("brainsos_telemetry.system.get_repo_root", return_value=str(tmp_path)):
        app = create_system_api_app()
        client = TestClient(app)
        csrf_tok = issue_csrf_token()
        headers = {
            "X-BrainsOS-Internal": "test-secret-token-12345",
            "X-Authentik-Username": "jsm",
            "X-CSRF-Token": csrf_tok,
            "Origin": "http://localhost",
        }

        up_res = client.post("/api/v1/system/os-upgrade", json={"dry_run": True}, headers=headers)
        assert up_res.status_code == 200
        assert "--os-only --unattended --dry-run" in up_res.text

        rb_res = client.post("/api/v1/system/reboot", json={"dry_run": True, "confirm": True}, headers=headers)
        assert rb_res.status_code == 200
        assert "REBOOT_ARGS: --unattended --dry-run" in rb_res.text


def test_terminal_exec_and_websocket_pty(tmp_path):
    with patch("brainsos_telemetry.system.get_repo_root", return_value=str(tmp_path)):
        app = create_system_api_app()
        client = TestClient(app)
        csrf_tok = issue_csrf_token()
        headers = {
            "X-BrainsOS-Internal": "test-secret-token-12345",
            "X-Authentik-Username": "jsm",
            "X-CSRF-Token": csrf_tok,
            "Origin": "http://localhost",
        }

        # 1. HTTP exec endpoint
        exec_res = client.post(
            "/api/v1/system/terminal/exec",
            json={"command": "echo hello-host-terminal"},
            headers=headers,
        )
        assert exec_res.status_code == 200
        data = exec_res.json()
        assert "hello-host-terminal" in data["stdout"]
        assert data["exit_code"] == 0

        # 2. WebSocket PTY endpoint
        with client.websocket_connect(
            "/api/v1/system/terminal/ws",
            headers={
                "X-BrainsOS-Internal": "test-secret-token-12345",
                "X-Authentik-Username": "jsm",
            },
        ) as ws:
            ready_msg = ws.receive_json()
            assert ready_msg["type"] == "ready"
            assert ready_msg["user"] == "jsm"
            ws.send_json({"type": "ping"})
            # Read until pong arrives
            found_pong = False
            for _ in range(5):
                m = ws.receive_json()
                if m.get("type") == "pong":
                    found_pong = True
                    break
            assert found_pong is True




