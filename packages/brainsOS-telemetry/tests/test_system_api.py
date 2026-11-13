"""Regression tests for System API identity, unit_name, superuser_username, and Hermes config payloads."""

from unittest.mock import patch

import pytest
from brainsos_telemetry.system import (
    create_system_api_app,
    get_appliance_identity,
    issue_csrf_token,
)
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def setup_test_env(monkeypatch):
    monkeypatch.setenv("BRAINSOS_STAGE", "test")
    monkeypatch.setenv("SYSTEM_API_TOKEN", "test-secret-token-12345")


def test_superuser_username_never_defaults_to_admin(tmp_path, monkeypatch):
    """Verify superuser_username is '' when BRAINSOS_SUPERUSER_USERNAME is unset or 'admin'."""
    monkeypatch.delenv("BRAINSOS_SUPERUSER_USERNAME", raising=False)
    monkeypatch.delenv("BRAINSOS_ADMIN_USERNAME", raising=False)

    # 1. When unset in .env
    (tmp_path / ".env").write_text("BRAINSOS_DOMAIN=dgx.local.brainsos.ai\n", encoding="utf-8")
    ident_unset = get_appliance_identity(str(tmp_path))
    assert ident_unset["superuser_username"] == ""
    assert ident_unset["admin_username"] == "admin"

    # 2. When explicitly set to 'admin'
    (tmp_path / ".env").write_text(
        "BRAINSOS_DOMAIN=dgx.local.brainsos.ai\n"
        "BRAINSOS_SUPERUSER_USERNAME=admin\n"
        "BRAINSOS_ADMIN_USERNAME=admin\n",
        encoding="utf-8",
    )
    ident_admin = get_appliance_identity(str(tmp_path))
    assert ident_admin["superuser_username"] == ""
    assert ident_admin["admin_username"] == "admin"

    # 3. When set to a custom human superuser ('su')
    (tmp_path / ".env").write_text(
        "BRAINSOS_DOMAIN=dgx.local.brainsos.ai\n"
        "BRAINSOS_MAIL_DOMAIN=mail.dgx.local.brainsos.ai\n"
        "BRAINSOS_SUPERUSER_USERNAME=su\n"
        "BRAINSOS_SUPERUSER_NAME=Jane Smith\n",
        encoding="utf-8",
    )
    ident_su = get_appliance_identity(str(tmp_path))
    assert ident_su["superuser_username"] == "su"
    assert ident_su["superuser_name"] == "Jane Smith"
    assert ident_su["local_domain"] == "dgx.local.brainsos.ai"
    assert ident_su["mail_domain"] == "mail.dgx.local.brainsos.ai"
    assert ident_su["repo_root"] == str(tmp_path)
    assert "data_dir" in ident_su
    assert "console_user" in ident_su


def test_unit_name_in_identity_and_setup(tmp_path, monkeypatch):
    """Verify unit_name in /api/v1/system/identity and --unit-name passed by /api/v1/system/setup."""
    monkeypatch.delenv("BRAINSOS_UNIT_NAME", raising=False)
    (tmp_path / ".env").write_text(
        "BRAINSOS_URL=dgx.local.brainsos.ai\n"
        "BRAINSOS_LOCAL_DOMAIN=dgx.local.brainsos.ai\n",
        encoding="utf-8",
    )
    script_dir = tmp_path / "scripts" / "control"
    script_dir.mkdir(parents=True)
    set_domain_sh = script_dir / "set-domain.sh"
    set_domain_sh.write_text('#!/usr/bin/env bash\necho "SETUP_ARGS: $*"\n', encoding="utf-8")
    set_domain_sh.chmod(0o755)

    with patch("brainsos_telemetry.system.get_repo_root", return_value=str(tmp_path)):
        app = create_system_api_app()
        client = TestClient(app)
        csrf_tok = issue_csrf_token()
        headers = {
            "X-BrainsOS-Internal": "test-secret-token-12345",
            "X-Authentik-Username": "su",
            "X-CSRF-Token": csrf_tok,
            "Origin": "http://localhost",
        }

        # Default unit_name is 'Enterprise Agent Box'
        id_res = client.get("/api/v1/system/identity", headers=headers)
        assert id_res.status_code == 200
        assert id_res.json()["unit_name"] == "Enterprise Agent Box"

        # Custom unit_name in .env is returned
        (tmp_path / ".env").write_text(
            'BRAINSOS_UNIT_NAME="Sovereign GX10 Unit 01"\n'
            "BRAINSOS_URL=dgx.local.brainsos.ai\n"
            "BRAINSOS_LOCAL_DOMAIN=dgx.local.brainsos.ai\n",
            encoding="utf-8",
        )
        id_res2 = client.get("/api/v1/system/identity", headers=headers)
        assert id_res2.status_code == 200
        assert id_res2.json()["unit_name"] == "Sovereign GX10 Unit 01"

        # Posting unit_name to /api/v1/system/setup passes --unit-name to set-domain.sh
        setup_res = client.post(
            "/api/v1/system/setup",
            json={
                "unit_name": "Production Appliance Alpha",
                "local_domain": "alpha.aws.cloud.brainsos.ai",
                "tls_mode": "internal",
            },
            headers=headers,
        )
        assert setup_res.status_code == 200
        assert "--unit-name Production Appliance Alpha" in setup_res.text


def test_hermes_config_keys_dict_payload(tmp_path):
    """Verify POST /api/v1/system/runners/hermes/config accepts {'keys': {'FIRECRAWL_API_KEY': '...'}, 'restart_runner': False}."""
    (tmp_path / ".env").write_text("BRAINSOS_DATA_DIR=./data\n", encoding="utf-8")

    with patch("brainsos_telemetry.system.get_repo_root", return_value=str(tmp_path)):
        app = create_system_api_app()
        client = TestClient(app)
        csrf_tok = issue_csrf_token()
        headers = {
            "X-BrainsOS-Internal": "test-secret-token-12345",
            "X-Authentik-Username": "su",
            "X-CSRF-Token": csrf_tok,
            "Origin": "http://localhost",
        }

        raw_key = "fc-" + ("0" * 16)  # gitleaks:allow
        tavily_mock = "tvly-" + ("1" * 12)  # gitleaks:allow
        res = client.post(
            "/api/v1/system/runners/hermes/config",
            json={
                "keys": {
                    "FIRECRAWL_API_KEY": raw_key,
                    "TAVILY_API_KEY": tavily_mock,
                },
                "restart_runner": False,
            },
            headers=headers,
        )
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "updated"
        assert body["runners"]["hermes"]["firecrawl_configured"] is True
        assert body["runners"]["tool_keys"]["FIRECRAWL_API_KEY"]["configured"] is True
        assert body["runners"]["tool_keys"]["TAVILY_API_KEY"]["configured"] is True
        assert raw_key not in res.text


def test_websocket_pty_fallback_username_when_sso_header_absent(tmp_path, monkeypatch):
    """Verify /api/v1/system/terminal/ws falls back to BRAINSOS_SUPERUSER_USERNAME or 'admin' when SSO header is missing."""
    monkeypatch.setenv("BRAINSOS_SUPERUSER_USERNAME", "su")
    with patch("brainsos_telemetry.system.get_repo_root", return_value=str(tmp_path)):
        app = create_system_api_app()
        client = TestClient(app)
        with client.websocket_connect(
            "/api/v1/system/terminal/ws",
            headers={"X-BrainsOS-Internal": "test-secret-token-12345"},
        ) as ws:
            ready_msg = ws.receive_json()
            assert ready_msg["type"] == "ready"
            assert ready_msg["user"] == "su"
            banner_msg = ws.receive_json()
            assert banner_msg["type"] == "output"
            assert banner_msg["data"].startswith("\x1b[2J\x1b[H")
            assert "brainsOS Appliance Host Console" in banner_msg["data"]


def test_system_me_endpoint(tmp_path):
    """Verify GET /api/v1/system/me resolves SSO headers and falls back to configured superuser identity."""
    (tmp_path / ".env").write_text(
        "BRAINSOS_LOCAL_DOMAIN=jsm.aws.cloud.brainsos.ai\n"
        "BRAINSOS_SUPERUSER_USERNAME=jsm\n"
        "BRAINSOS_SUPERUSER_NAME=Jane Smith\n",
        encoding="utf-8",
    )
    with patch("brainsos_telemetry.system.get_repo_root", return_value=str(tmp_path)):
        app = create_system_api_app()
        client = TestClient(app)

        # 1. With Authentik headers
        res_sso = client.get(
            "/api/v1/system/me",
            headers={
                "X-BrainsOS-Internal": "test-secret-token-12345",
                "X-Authentik-Username": "jsm",
                "X-Authentik-Name": "Jane Smith",
                "X-Authentik-Email": "jsm@jsm.aws.cloud.brainsos.ai",
            },
        )
        assert res_sso.status_code == 200
        assert res_sso.json()["username"] == "jsm"
        assert res_sso.json()["name"] == "Jane Smith"
        assert res_sso.json()["email"] == "jsm@jsm.aws.cloud.brainsos.ai"

        # 2. Fallback to .env superuser identity when headers are absent
        res_fb = client.get(
            "/api/v1/system/me",
            headers={"X-BrainsOS-Internal": "test-secret-token-12345"},
        )
        assert res_fb.status_code == 200
        assert res_fb.json()["username"] == "jsm"
        assert res_fb.json()["name"] == "Jane Smith"
        assert res_fb.json()["email"] == "jsm@jsm.aws.cloud.brainsos.ai"


def test_userdata_routing_preserved_during_wizard_setup(tmp_path, monkeypatch):
    """Verify User-Data DNS/SSL settings are exposed and preserved when creating Superuser (#373)."""
    mock_iid = "i-0" + ("b" * 16)
    monkeypatch.setenv("BRAINSOS_TEST_INSTANCE_ID", mock_iid)
    (tmp_path / ".env").write_text(
        "BRAINSOS_URL=alice.demo.infotechlabs.io\n"
        "BRAINSOS_DOMAIN=alice.demo.infotechlabs.io\n"
        "BRAINSOS_LOCAL_DOMAIN=alice.demo.infotechlabs.io\n"
        "BRAINSOS_TLS_MODE=acme\n"
        "ACME_EMAIL=ops@infotechlabs.io\n"
        "BRAINSOS_ROUTE53_ZONE_ID=Z0987654321DEMO\n"
        "BRAINSOS_USERDATA_ROUTING=true\n"
        "BRAINSOS_ADMIN_USERNAME=admin\n"
        f"BRAINSOS_ADMIN_PASSWORD={mock_iid}\n"
        f"BRAINSOS_INSTANCE_ID={mock_iid}\n"
        "BRAINSOS_WIZARD_COMPLETED=false\n",
        encoding="utf-8",
    )
    script_dir = tmp_path / "scripts" / "control"
    script_dir.mkdir(parents=True)
    set_domain_sh = script_dir / "set-domain.sh"
    set_domain_sh.write_text('#!/usr/bin/env bash\necho "UD_SETUP_ARGS: $*"\n', encoding="utf-8")
    set_domain_sh.chmod(0o755)

    with patch("brainsos_telemetry.system.get_repo_root", return_value=str(tmp_path)):
        app = create_system_api_app()
        client = TestClient(app)
        csrf_tok = issue_csrf_token()
        headers = {
            "X-BrainsOS-Internal": "test-secret-token-12345",
            "X-CSRF-Token": csrf_tok,
            "Origin": "http://localhost",
        }

        id_res = client.get("/api/v1/system/identity", headers=headers)
        assert id_res.status_code == 200
        ident = id_res.json()
        assert ident["userdata_routing_configured"] is True
        assert ident["route53_zone_id"] == "Z0987654321DEMO"
        assert ident["url"] == "alice.demo.infotechlabs.io"
        assert ident["local_domain"] == "alice.demo.infotechlabs.io"
        assert ident["tls_mode"] == "acme"
        assert ident["acme_email"] == "ops@infotechlabs.io"

        # Submitting Superuser + Unit Name preserves alice.demo.infotechlabs.io + ACME TLS
        setup_res = client.post(
            "/api/v1/system/setup",
            json={
                "bootstrap_token": mock_iid,
                "unit_name": "Alice Demo Box",
                "superuser_name": "Alice Operator",
                "superuser_username": "alice",
                "superuser_password": "StrongUserPass99!",
            },
            headers=headers,
        )
        assert setup_res.status_code == 200
        assert "--url alice.demo.infotechlabs.io" in setup_res.text
        assert "--local-domain alice.demo.infotechlabs.io" in setup_res.text
        assert "--email ops@infotechlabs.io" in setup_res.text
        assert "--internal" not in setup_res.text
        assert "aws.cloud.brainsos.ai" not in setup_res.text
