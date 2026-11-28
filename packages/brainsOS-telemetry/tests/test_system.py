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

    unauth_res = client.get(
        "/api/v1/system/status",
        headers={"X-BrainsOS-Internal": "test-secret-token-12345"},
    )
    assert unauth_res.status_code == 403

    headers = {
        "X-BrainsOS-Internal": "test-secret-token-12345",
        "X-Authentik-Username": "su",
        "X-Authentik-Groups": "authentik Admins",
    }
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

        unauth_res = client.get(
            "/api/v1/system/jobs/nonexistent-id",
            headers={"X-BrainsOS-Internal": "test-secret-token-12345"},
        )
        assert unauth_res.status_code == 403

        admin_headers = {
            "X-BrainsOS-Internal": "test-secret-token-12345",
            "X-Authentik-Username": "su",
            "X-Authentik-Groups": "authentik Admins",
        }
        res = client.get("/api/v1/system/jobs/nonexistent-id", headers=admin_headers)
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
        "BRAINSOS_TLS_MODE=internal\n"
        "BRAINSOS_BOOTSTRAP_TOKEN=bt-test-bootstrap-123456\n",
        encoding="utf-8",
    )
    (tmp_path / ".brainsos-initialized").write_text("2026-11-06T00:00:00Z\n", encoding="utf-8")

    with patch("brainsos_telemetry.system.get_repo_root", return_value=str(tmp_path)):
        app = create_system_api_app()
        client = TestClient(app, base_url="https://testserver")
        headers = {"X-BrainsOS-Internal": "test-secret-token-12345"}

        # Unauthenticated pre-wizard /identity returns strictly 4 minimal keys
        res = client.get("/api/v1/system/identity", headers=headers)
        assert res.status_code == 200
        ident = res.json()
        assert set(ident.keys()) == {
            "firstboot_wizard_completed",
            "unit_name",
            "url",
            "tls_mode",
        }
        assert ident["firstboot_wizard_completed"] is False
        assert ident["url"] == "ec2-32-192-215-107.compute-1.amazonaws.com"

        # Mint wizard session cookie via /firstboot/session -> full pre-wizard /identity unlocked
        csrf_tok = issue_csrf_token()
        sess_res = client.post(
            "/api/v1/system/firstboot/session",
            json={"bootstrap_token": "bt-test-bootstrap-123456"},
            headers={
                **headers,
                "X-CSRF-Token": csrf_tok,
                "Origin": "http://localhost",
            },
        )
        assert sess_res.status_code == 200
        res_full = client.get("/api/v1/system/identity", headers=headers)
        assert res_full.status_code == 200
        full_ident = res_full.json()
        assert full_ident["local_domain"] == "jsm.cloud.aws.brainsos.ai"
        assert full_ident["admin_username"] == "jsm"
        assert full_ident["admin_email"] == "jsm@jsm.cloud.aws.brainsos.ai"

        # Dismiss wizard via POST /api/v1/system/setup
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
    mock_iid = "i-0" + ("a" * 16)
    monkeypatch.setenv("BRAINSOS_TEST_INSTANCE_ID", mock_iid)
    (tmp_path / ".env").write_text(
        "BRAINSOS_URL=ec2-32-192-215-107.compute-1.amazonaws.com\n"
        "BRAINSOS_LOCAL_DOMAIN=local.brainsos.ai\n"
        "BRAINSOS_ADMIN_USERNAME=admin\n"
        f"BRAINSOS_ADMIN_PASSWORD={mock_iid}\n"
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

        # 1. GET /api/v1/system/identity returns strictly 4 minimal keys before wizard session auth
        ident_res = client.get("/api/v1/system/identity", headers=prelogin_headers)
        assert ident_res.status_code == 200
        assert set(ident_res.json().keys()) == {
            "firstboot_wizard_completed",
            "unit_name",
            "url",
            "tls_mode",
        }
        assert ident_res.json()["firstboot_wizard_completed"] is False
        assert "instance_id" not in ident_res.json()

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

        # 3. Valid EC2 Instance ID bootstrap_token succeeds pre-login and sets wizard cookie
        ok_token_res = client.post(
            "/api/v1/system/setup",
            json={
                "bootstrap_token": mock_iid,
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
        assert "brainsos_wizard_session" in ok_token_res.cookies


def test_superuser_setup_and_password_complexity(tmp_path, monkeypatch):
    from brainsos_telemetry.system import validate_password_complexity

    mock_iid = "i-0" + ("a" * 16)
    assert validate_password_complexity("short1!") is not None
    assert validate_password_complexity("alllowercase123!") is not None
    assert validate_password_complexity("ALLUPPERCASE123!") is not None
    assert validate_password_complexity("NoDigitsHere!") is not None
    assert validate_password_complexity("NoSpecialChars123") is not None
    assert validate_password_complexity(mock_iid, instance_id=mock_iid) is not None
    assert validate_password_complexity("ValidSuperPass99!", username="jsm", instance_id=mock_iid) is None

    monkeypatch.setenv("BRAINSOS_TEST_INSTANCE_ID", mock_iid)
    (tmp_path / ".env").write_text(
        "BRAINSOS_URL=ec2-32-192-215-107.compute-1.amazonaws.com\n"
        "BRAINSOS_LOCAL_DOMAIN=local.brainsos.ai\n"
        "BRAINSOS_ADMIN_USERNAME=admin\n"
        f"BRAINSOS_ADMIN_PASSWORD={mock_iid}\n"
        f"BRAINSOS_INSTANCE_ID={mock_iid}\n"
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
        assert "reserved for system break-glass" in admin_res.json().get("detail", "")

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
        raw_key = "fc-9" + ("0" * 16)  # gitleaks:allow
        r2 = client.post(
            "/api/v1/system/runners/hermes/config",
            json={"firecrawl_api_key": raw_key, "restart_runner": False},
            headers=headers,
        )
        assert r2.status_code == 200
        body = r2.json()
        assert body["status"] == "updated"
        assert body["runners"]["hermes"]["firecrawl_configured"] is True
        assert body["runners"]["tool_keys"]["FIRECRAWL_API_KEY"] == {"configured": True}
        assert "masked" not in body["runners"]["tool_keys"]["FIRECRAWL_API_KEY"]
        assert "fc-9" not in r2.text
        assert raw_key not in r2.text

        r3 = client.get("/api/v1/system/runners", headers=headers)
        assert r3.status_code == 200
        assert r3.json()["tool_keys"]["FIRECRAWL_API_KEY"] == {"configured": True}
        assert "masked" not in r3.text

        st = client.get("/api/v1/system/status", headers=headers)
        assert st.status_code == 200
        assert st.json()["runners"]["tool_keys"]["FIRECRAWL_API_KEY"] == {"configured": True}
        assert "fc-9" not in st.text


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


@pytest.mark.asyncio
async def test_job_status_and_stream_reattach_require_system_auth_for_latest_and_active(tmp_path):
    """Verify /jobs/{latest,active} and /jobs/{latest,active}/stream require admin auth post-wizard."""
    from brainsos_telemetry.system import JobManager

    (tmp_path / ".env").write_text(
        "BRAINSOS_DOMAIN=box.brainsos.ai\nBRAINSOS_WIZARD_COMPLETED=true\n",
        encoding="utf-8",
    )
    (tmp_path / ".brainsos-wizard-completed").write_text("2026-11-26T00:00:00Z\n", encoding="utf-8")

    # Seed a completed job record and log file
    jm = JobManager(str(tmp_path))
    job = await jm.start_job("update", ["echo", "reattach-ok"])
    await job["task"]

    with patch("brainsos_telemetry.system.get_repo_root", return_value=str(tmp_path)):
        app = create_system_api_app()
        client = TestClient(app, base_url="https://testserver")

        internal_headers = {"X-BrainsOS-Internal": "test-secret-token-12345"}
        viewer_headers = {
            **internal_headers,
            "X-Authentik-Username": "viewer",
            "X-Authentik-Groups": "brainsos-viewers",
        }
        admin_headers = {
            **internal_headers,
            "X-Authentik-Username": "su",
            "X-Authentik-Groups": "authentik Admins",
        }

        for endpoint in (
            "/api/v1/system/jobs/latest",
            "/api/v1/system/jobs/active",
            f"/api/v1/system/jobs/{job['id']}",
            "/api/v1/system/jobs/latest/stream",
            "/api/v1/system/jobs/active/stream",
            f"/api/v1/system/jobs/{job['id']}/stream",
        ):
            assert client.get(endpoint, headers=internal_headers).status_code == 403
            assert client.get(endpoint, headers=viewer_headers).status_code == 403

        # Admin can access /jobs/latest, /jobs/{id}, and streams
        latest_res = client.get("/api/v1/system/jobs/latest", headers=admin_headers)
        assert latest_res.status_code == 200
        assert latest_res.json()["id"] == job["id"]

        id_res = client.get(f"/api/v1/system/jobs/{job['id']}", headers=admin_headers)
        assert id_res.status_code == 200
        assert id_res.json()["id"] == job["id"]

        stream_res = client.get("/api/v1/system/jobs/latest/stream", headers=admin_headers)
        assert stream_res.status_code == 200
        assert "reattach-ok" in stream_res.text

        # Pre-wizard mode still blocks raw unauthenticated /jobs/* access (#405),
        # requiring a short-lived brainsos_wizard_session cookie minted via /firstboot/session.
        (tmp_path / ".brainsos-wizard-completed").unlink()
        (tmp_path / ".env").write_text(
            "BRAINSOS_DOMAIN=box.brainsos.ai\n"
            "BRAINSOS_WIZARD_COMPLETED=false\n"
            "BRAINSOS_BOOTSTRAP_TOKEN=i-wizard-job-token-123\n",
            encoding="utf-8",
        )
        for endpoint in (
            "/api/v1/system/jobs/latest",
            f"/api/v1/system/jobs/{job['id']}",
            "/api/v1/system/jobs/latest/stream",
            f"/api/v1/system/jobs/{job['id']}/stream",
        ):
            assert client.get(endpoint, headers=internal_headers).status_code == 403

        csrf_tok = issue_csrf_token()
        sess_res = client.post(
            "/api/v1/system/firstboot/session",
            json={"bootstrap_token": "i-wizard-job-token-123"},
            headers={**internal_headers, "X-CSRF-Token": csrf_tok, "Origin": "http://localhost"},
        )
        assert sess_res.status_code == 200
        pre_res = client.get("/api/v1/system/jobs/latest", headers=internal_headers)
        assert pre_res.status_code == 200
        pre_id_res = client.get(f"/api/v1/system/jobs/{job['id']}", headers=internal_headers)
        assert pre_id_res.status_code == 200
        pre_stream = client.get("/api/v1/system/jobs/latest/stream", headers=internal_headers)
        assert pre_stream.status_code == 200
        pre_id_stream = client.get(f"/api/v1/system/jobs/{job['id']}/stream", headers=internal_headers)
        assert pre_id_stream.status_code == 200


@pytest.mark.asyncio
async def test_get_system_status_120s_ttl_cache_and_bounds(tmp_path):
    """Verify 120s TTL cache on update.sh --check --json, fresh identity overlay, non-caching of errors, and max entries."""
    import json
    import subprocess
    from unittest.mock import MagicMock

    from brainsos_telemetry import system as sys_mod

    sys_mod.clear_update_check_cache()
    (tmp_path / ".env").write_text("BRAINSOS_UNIT_NAME=Box One\n", encoding="utf-8")
    script_dir = tmp_path / "scripts" / "control"
    script_dir.mkdir(parents=True)
    update_sh = script_dir / "update.sh"
    update_sh.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    update_sh.chmod(0o755)

    calls = []
    now_clock = [1000.0]

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        payload = {
            "platform": "brainsOS",
            "git": {"branch": "main", "update_available": False},
            "services": {},
            "disk": {"total_gb": 100.0, "used_gb": 20.0, "free_gb": 80.0, "free_pct": 80.0, "warning": False},
            "overall_update_available": False,
        }
        m = MagicMock(spec=subprocess.CompletedProcess)
        m.returncode = 0
        m.stdout = json.dumps(payload)
        m.stderr = ""
        return m

    with (
        patch("brainsos_telemetry.system.get_repo_root", return_value=str(tmp_path)),
        patch("brainsos_telemetry.system.time.monotonic", side_effect=lambda: now_clock[0]),
        patch("brainsos_telemetry.system.subprocess.run", side_effect=fake_run),
    ):
        # 1. First async call invokes update.sh once
        s1 = await sys_mod.get_system_status_async()
        assert s1["unit_name"] == "Box One"
        assert len(calls) == 1

        # 2. Mutate unit_name and call again within 120s -> cache hit for update.sh, fresh identity!
        (tmp_path / ".env").write_text("BRAINSOS_UNIT_NAME=Box Two\n", encoding="utf-8")
        now_clock[0] = 1050.0
        s2 = await sys_mod.get_system_status_async()
        assert s2["unit_name"] == "Box Two"
        assert len(calls) == 1

        # 3. Advance past 120s -> cache expires and re-runs update.sh
        now_clock[0] = 1125.0
        s3 = sys_mod.get_system_status()
        assert s3["unit_name"] == "Box Two"
        assert len(calls) == 2

    # 4. Non-zero exit code is NOT cached
    sys_mod.clear_update_check_cache()
    fail_calls = []

    def fake_fail(cmd, **kwargs):
        fail_calls.append(cmd)
        m = MagicMock(spec=subprocess.CompletedProcess)
        m.returncode = 1
        m.stdout = ""
        m.stderr = "boom"
        return m

    with (
        patch("brainsos_telemetry.system.get_repo_root", return_value=str(tmp_path)),
        patch("brainsos_telemetry.system.subprocess.run", side_effect=fake_fail),
    ):
        _ = await sys_mod.get_system_status_async()
        _ = await sys_mod.get_system_status_async()
        assert len(fail_calls) == 2

    # 5. Bounded eviction at UPDATE_CHECK_CACHE_MAX_ENTRIES
    sys_mod.clear_update_check_cache()
    for i in range(sys_mod.UPDATE_CHECK_CACHE_MAX_ENTRIES + 5):
        sys_mod._write_cached_update_check(f"/repo/{i}", {"disk": {}}, float(100 + i))
    assert len(sys_mod._UPDATE_CHECK_CACHE) == sys_mod.UPDATE_CHECK_CACHE_MAX_ENTRIES
    sys_mod.clear_update_check_cache()


def test_prewizard_redaction_status_and_identity_expose_only_4_keys(tmp_path, monkeypatch):
    """Verify unauthenticated pre-wizard /status and /identity return only the 4 minimal keys (#405)."""
    mock_iid = "bt-0123456789abcdef0123456789abcdef"
    monkeypatch.setenv("BRAINSOS_TEST_INSTANCE_ID", mock_iid)
    (tmp_path / ".env").write_text(
        "BRAINSOS_STAGE=test\n"
        "BRAINSOS_WIZARD_COMPLETED=false\n"
        "BRAINSOS_UNIT_NAME=My Unit\n"
        "BRAINSOS_URL=alice.brainsos.ai\n"
        "BRAINSOS_LOCAL_DOMAIN=alice.brainsos.ai\n"
        "BRAINSOS_TLS_MODE=acme\n"
        "BRAINSOS_ADMIN_EMAIL=secret-admin@example.com\n"
        "BRAINSOS_USER_SUB=sub-secret-123\n"
        "BRAINSOS_ROUTE53_ZONE_ID=Z123SECRET\n"
        "BRAINSOS_USERDATA_ROUTING=true\n"
        f"BRAINSOS_BOOTSTRAP_TOKEN={mock_iid}\n"
        f"BRAINSOS_INSTANCE_ID={mock_iid}\n",
        encoding="utf-8",
    )

    with patch("brainsos_telemetry.system.get_repo_root", return_value=str(tmp_path)):
        app = create_system_api_app()
        client = TestClient(app)
        headers = {"X-BrainsOS-Internal": "test-secret-token-12345"}

        for path in ("/api/v1/system/identity", "/api/v1/system/status"):
            res = client.get(path, headers=headers)
            assert res.status_code == 200
            data = res.json()
            assert set(data.keys()) == {"firstboot_wizard_completed", "unit_name", "url", "tls_mode"}
            assert data["firstboot_wizard_completed"] is False
            assert data["unit_name"] == "My Unit"
            assert data["url"] == "alice.brainsos.ai"
            assert data["tls_mode"] == "acme"
            for forbidden_key in (
                "os",
                "disk",
                "runners",
                "admin_email",
                "user_sub",
                "local_domain",
                "instance_id",
                "route53_zone_id",
                "userdata_routing_configured",
            ):
                assert forbidden_key not in data
            for forbidden_val in ("secret-admin@example.com", "sub-secret-123", "Z123SECRET", mock_iid):
                assert forbidden_val not in res.text


def test_firstboot_session_lockout_and_cookie_enables_pre_sso_polling(tmp_path, monkeypatch):
    """Verify 5-attempt 429 lockout, Retry-After, HttpOnly/Secure/SameSite=Strict cookie, and pre-SSO polling (#405)."""
    boot_tok = "bt-" + ("a" * 32)
    monkeypatch.setenv("BRAINSOS_TEST_INSTANCE_ID", "")
    (tmp_path / ".env").write_text(
        "BRAINSOS_STAGE=test\n"
        "BRAINSOS_WIZARD_COMPLETED=false\n"
        "BRAINSOS_LOCAL_DOMAIN=alice.brainsos.ai\n"
        "BRAINSOS_URL=alice.brainsos.ai\n"
        f"BRAINSOS_BOOTSTRAP_TOKEN={boot_tok}\n",
        encoding="utf-8",
    )

    with patch("brainsos_telemetry.system.get_repo_root", return_value=str(tmp_path)):
        app = create_system_api_app()
        client = TestClient(app, base_url="https://testserver")
        csrf_tok = issue_csrf_token()
        attacker_headers = {
            "X-BrainsOS-Internal": "test-secret-token-12345",
            "X-CSRF-Token": csrf_tok,
            "Origin": "http://localhost",
            "X-Forwarded-For": "1.2.3.4, 198.51.100.10",
        }

        # Attempts 1-4 fail with 403; attempt 5 locks IP out with 429 + Retry-After
        for attempt in range(4):
            r = client.post(
                "/api/v1/system/firstboot/session",
                json={"bootstrap_token": f"wrong-token-{attempt}"},
                headers=attacker_headers,
            )
            assert r.status_code == 403

        r5 = client.post(
            "/api/v1/system/firstboot/session",
            json={"bootstrap_token": "wrong-token-4"},
            headers=attacker_headers,
        )
        assert r5.status_code == 429
        assert int(r5.headers.get("Retry-After", "0")) >= 1

        # Even valid bootstrap_token is blocked during lockout (and leftmost spoofed XFF cannot bypass)
        r_locked = client.post(
            "/api/v1/system/firstboot/session",
            json={"bootstrap_token": boot_tok},
            headers={**attacker_headers, "X-Forwarded-For": "9.9.9.9, 198.51.100.10"},
        )
        assert r_locked.status_code == 429

        # Independent client IP succeeds, sets hardened cookie, and enables pre-SSO polling
        legit_headers = {
            "X-BrainsOS-Internal": "test-secret-token-12345",
            "X-CSRF-Token": csrf_tok,
            "Origin": "http://localhost",
            "X-Real-IP": "203.0.113.55",
        }
        ok_res = client.post(
            "/api/v1/system/firstboot/session",
            json={"bootstrap_token": boot_tok},
            headers=legit_headers,
        )
        assert ok_res.status_code == 200
        set_cookie = ok_res.headers.get("set-cookie", "")
        assert "brainsos_wizard_session=" in set_cookie
        assert "httponly" in set_cookie.lower()
        assert "secure" in set_cookie.lower()
        assert "samesite=strict" in set_cookie.lower()

        st_res = client.get("/api/v1/system/status", headers={"X-BrainsOS-Internal": "test-secret-token-12345"})
        assert st_res.status_code == 200
        assert "disk" in st_res.json()
        assert "os" in st_res.json()

        dns_res = client.post(
            "/api/v1/system/dns-check",
            json={"domain": "localhost"},
            headers=legit_headers,
        )
        assert dns_res.status_code == 200


def test_dismiss_only_and_post_wizard_disable_bootstrap_and_enforce_viewer_rbac(tmp_path, monkeypatch):
    """Verify dismiss_only disables bootstrap & breakglass, clears wizard cookie, and post-wizard viewer RBAC holds (#405)."""
    boot_tok = "bt-" + ("b" * 32)
    monkeypatch.setenv("BRAINSOS_TEST_INSTANCE_ID", "i-09998887776665554")
    (tmp_path / ".env").write_text(
        "BRAINSOS_STAGE=test\n"
        "BRAINSOS_WIZARD_COMPLETED=false\n"
        "BRAINSOS_BREAKGLASS_ENABLED=true\n"
        "BRAINSOS_SUPERUSER_USERNAME=alice\n"
        "BRAINSOS_DOMAIN=alice.brainsos.ai\n"
        f"BRAINSOS_BOOTSTRAP_TOKEN={boot_tok}\n"
        "BRAINSOS_INSTANCE_ID=i-09998887776665554\n",
        encoding="utf-8",
    )

    with patch("brainsos_telemetry.system.get_repo_root", return_value=str(tmp_path)):
        app = create_system_api_app()
        client = TestClient(app, base_url="https://testserver")
        csrf_tok = issue_csrf_token()
        internal_headers = {
            "X-BrainsOS-Internal": "test-secret-token-12345",
            "X-CSRF-Token": csrf_tok,
            "Origin": "http://localhost",
        }

        sess_res = client.post(
            "/api/v1/system/firstboot/session",
            json={"bootstrap_token": boot_tok},
            headers=internal_headers,
        )
        assert sess_res.status_code == 200

        dismiss_res = client.post(
            "/api/v1/system/setup",
            json={"bootstrap_token": boot_tok, "dismiss_only": True},
            headers=internal_headers,
        )
        assert dismiss_res.status_code == 200
        env_text = (tmp_path / ".env").read_text(encoding="utf-8")
        assert "BRAINSOS_WIZARD_COMPLETED=true" in env_text
        assert "BRAINSOS_BREAKGLASS_ENABLED=false" in env_text

        # Bootstrap token and wizard cookie are permanently rejected post-wizard
        retry_sess = client.post(
            "/api/v1/system/firstboot/session",
            json={"bootstrap_token": boot_tok},
            headers=internal_headers,
        )
        assert retry_sess.status_code == 403
        retry_setup = client.post(
            "/api/v1/system/setup",
            json={"bootstrap_token": "i-09998887776665554", "local_domain": "evil.example.com", "url": "evil.example.com"},
            headers=internal_headers,
        )
        assert retry_setup.status_code == 403
        assert client.get("/api/v1/system/status", headers={"X-BrainsOS-Internal": "test-secret-token-12345"}).status_code == 403

        # Non-admin brainsos-viewers can access /me (is_superuser=False) & minimal /identity, blocked on admin routes
        viewer_headers = {
            **internal_headers,
            "X-Authentik-Username": "bob",
            "X-Authentik-Groups": "brainsos-viewers",
        }
        me_res = client.get("/api/v1/system/me", headers=viewer_headers)
        assert me_res.status_code == 200
        assert me_res.json()["is_superuser"] is False

        id_res = client.get("/api/v1/system/identity", headers=viewer_headers)
        assert id_res.status_code == 200
        assert set(id_res.json().keys()) == {"firstboot_wizard_completed", "unit_name", "auth_cognito_enabled"}

        for blocked_get in ("/api/v1/system/status", "/api/v1/system/runners", "/api/v1/system/jobs/nonexistent"):
            assert client.get(blocked_get, headers=viewer_headers).status_code == 403
        assert (
            client.post("/api/v1/system/dns-check", json={"domain": "localhost"}, headers=viewer_headers).status_code
            == 403
        )


def test_is_authorized_admin_and_me_fail_closed_when_groups_missing_in_prod(tmp_path, monkeypatch):
    """Verify _is_authorized_admin and /me fail closed outside BRAINSOS_STAGE=test when groups/username missing (#405)."""
    from brainsos_telemetry import system as sys_mod

    monkeypatch.setenv("BRAINSOS_STAGE", "production")
    (tmp_path / ".env").write_text(
        "BRAINSOS_STAGE=production\n"
        "BRAINSOS_WIZARD_COMPLETED=true\n"
        "BRAINSOS_SUPERUSER_USERNAME=alice\n"
        "BRAINSOS_DOMAIN=alice.brainsos.ai\n",
        encoding="utf-8",
    )
    (tmp_path / ".brainsos-wizard-completed").write_text("2026-11-27T00:00:00Z\n", encoding="utf-8")

    assert sys_mod._is_authorized_admin({"X-Authentik-Username": "alice"}, "alice", str(tmp_path)) is False
    assert (
        sys_mod._is_authorized_admin(
            {"X-Authentik-Username": "alice", "X-Authentik-Groups": "authentik Admins"},
            "alice",
            str(tmp_path),
        )
        is True
    )

    with patch("brainsos_telemetry.system.get_repo_root", return_value=str(tmp_path)):
        app = create_system_api_app()
        client = TestClient(app)
        internal_headers = {"X-BrainsOS-Internal": "test-secret-token-12345"}

        assert client.get("/api/v1/system/me", headers=internal_headers).status_code == 403
        assert (
            client.get(
                "/api/v1/system/status",
                headers={**internal_headers, "X-Authentik-Username": "alice"},
            ).status_code
            == 403
        )
        assert (
            client.get(
                "/api/v1/system/status",
                headers={
                    **internal_headers,
                    "X-Authentik-Username": "alice",
                    "X-Authentik-Groups": "authentik Admins",
                },
            ).status_code
            == 200
        )


def test_firstboot_session_x_real_ip_spoofing_cannot_bypass_lockout(tmp_path, monkeypatch):
    """Verify rotating spoofed X-Real-IP with constant X-Forwarded-For still triggers 429 lockout (#405)."""
    boot_tok = "bt-" + ("c" * 32)
    monkeypatch.setenv("BRAINSOS_TEST_INSTANCE_ID", "")
    (tmp_path / ".env").write_text(
        "BRAINSOS_STAGE=test\n"
        "BRAINSOS_WIZARD_COMPLETED=false\n"
        "BRAINSOS_LOCAL_DOMAIN=alice.brainsos.ai\n"
        "BRAINSOS_URL=alice.brainsos.ai\n"
        f"BRAINSOS_BOOTSTRAP_TOKEN={boot_tok}\n",
        encoding="utf-8",
    )

    with patch("brainsos_telemetry.system.get_repo_root", return_value=str(tmp_path)):
        app = create_system_api_app()
        client = TestClient(app, base_url="https://testserver")
        csrf_tok = issue_csrf_token()
        base_headers = {
            "X-BrainsOS-Internal": "test-secret-token-12345",
            "X-CSRF-Token": csrf_tok,
            "Origin": "http://localhost",
            "X-Forwarded-For": "203.0.113.99",
        }

        statuses = []
        for idx in range(1, 6):
            res = client.post(
                "/api/v1/system/firstboot/session",
                json={"bootstrap_token": f"wrong-token-{idx}"},
                headers={**base_headers, "X-Real-IP": f"10.0.0.{idx}"},
            )
            statuses.append(res.status_code)

        assert statuses == [403, 403, 403, 403, 429]

        valid_res = client.post(
            "/api/v1/system/firstboot/session",
            json={"bootstrap_token": boot_tok},
            headers={**base_headers, "X-Real-IP": "10.0.0.250"},
        )
        assert valid_res.status_code == 429
