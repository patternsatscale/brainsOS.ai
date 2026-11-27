"""Regression tests for Ticket #385: ALB OIDC ES256 pass-through, owner binding, break-glass & RBAC hardening."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Dict, Tuple
from unittest.mock import patch

import jwt
import pytest
from brainsos_telemetry.alb_auth import (
    AlbAuthError,
    authenticate_alb_headers,
    clear_key_cache,
    validate_breakglass_toggle,
)
from brainsos_telemetry.system import create_system_api_app, issue_csrf_token
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[3]
SAMPLE_SIGNER_ARN = (
    "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/brainsos-alb/0123456789abcdef"
)
SAMPLE_KID = "9c7b2a10-1234-4abc-9def-0123456789ab"


def _make_ec_keypair() -> Tuple[ec.EllipticCurvePrivateKey, str]:
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return private_key, public_pem


def _sign_alb_jwt(
    private_key: ec.EllipticCurvePrivateKey,
    payload: Dict[str, Any],
    *,
    kid: str = SAMPLE_KID,
    signer: str = SAMPLE_SIGNER_ARN,
    alg: str = "ES256",
) -> str:
    return jwt.encode(
        payload,
        private_key,
        algorithm=alg,
        headers={"kid": kid, "signer": signer, "alg": alg},
    )


@pytest.fixture(autouse=True)
def _clean_auth_env(monkeypatch):
    clear_key_cache()
    monkeypatch.setenv("SYSTEM_API_TOKEN", "test-secret-token-12345")
    monkeypatch.setenv("BRAINSOS_STAGE", "test")
    yield
    clear_key_cache()


def test_alb_jwt_owner_elevation_without_cognito_admin_group():
    """Matching BRAINSOS_USER_SUB elevates to authentik Admins even with zero Cognito admin groups."""
    priv, pub_pem = _make_ec_keypair()
    token = _sign_alb_jwt(
        priv,
        {
            "sub": "c0gni70-user-sub-owner",
            "preferred_username": "alice",
            "email": "alice@example.com",
            "name": "Alice Owner",
            "cognito:groups": [],
            "exp": int(time.time()) + 300,
        },
    )
    env = {
        "AUTH_ALB_OIDC_ENABLED": "true",
        "AUTH_ALB_SIGNER_ARN": SAMPLE_SIGNER_ARN,
        "BRAINSOS_USER_SUB": "c0gni70-user-sub-owner",
        "BRAINSOS_OWNER_ONLY": "true",
        "AUTH_COGNITO_ADMIN_GROUP": "brainsos-admins",
    }

    res = authenticate_alb_headers(
        {"X-Amzn-Oidc-Data": token},
        env,
        key_fetcher=lambda _region, _kid: pub_pem,
    )
    assert res["is_owner"] is True
    assert res["is_admin"] is True
    assert res["headers"]["X-Authentik-Groups"] == "authentik Admins"
    assert res["headers"]["X-BrainsOS-Owner"] == "true"
    assert res["headers"]["X-Authentik-Username"] == "alice"
    assert res["headers"]["X-Authentik-Uid"] == "c0gni70-user-sub-owner"


def test_alb_jwt_non_owner_rejected_when_owner_only_or_viewer_when_disabled():
    """Non-matching sub is rejected 403 when BRAINSOS_OWNER_ONLY=true, or gets viewer when false."""
    priv, pub_pem = _make_ec_keypair()
    token = _sign_alb_jwt(
        priv,
        {
            "sub": "other-user-sub-999",
            "preferred_username": "bob",
            "email": "bob@example.com",
            "exp": int(time.time()) + 300,
        },
    )
    base_env = {
        "AUTH_ALB_OIDC_ENABLED": "true",
        "AUTH_ALB_SIGNER_ARN": SAMPLE_SIGNER_ARN,
        "BRAINSOS_USER_SUB": "c0gni70-user-sub-owner",
        "BRAINSOS_OWNER_ONLY": "true",
    }

    with pytest.raises(AlbAuthError) as exc_info:
        authenticate_alb_headers(
            {"X-Amzn-Oidc-Data": token},
            base_env,
            key_fetcher=lambda _r, _k: pub_pem,
        )
    assert exc_info.value.status_code == 403

    viewer_res = authenticate_alb_headers(
        {"X-Amzn-Oidc-Data": token},
        {**base_env, "BRAINSOS_OWNER_ONLY": "false"},
        key_fetcher=lambda _r, _k: pub_pem,
    )
    assert viewer_res["is_owner"] is False
    assert viewer_res["is_admin"] is False
    assert viewer_res["headers"]["X-Authentik-Groups"] == "brainsos-viewers"
    assert viewer_res["headers"]["X-BrainsOS-Owner"] == "false"


def test_alb_jwt_cognito_admin_group_grants_admin():
    """Membership in AUTH_COGNITO_ADMIN_GROUP grants authentik Admins on shared/team boxes."""
    priv, pub_pem = _make_ec_keypair()
    token = _sign_alb_jwt(
        priv,
        {
            "sub": "pool-admin-sub",
            "email": "ops@example.com",
            "cognito:groups": ["brainsos-admins"],
            "exp": int(time.time()) + 300,
        },
    )
    env = {
        "AUTH_ALB_OIDC_ENABLED": "true",
        "AUTH_ALB_SIGNER_ARN": SAMPLE_SIGNER_ARN,
        "BRAINSOS_USER_SUB": "different-owner-sub",
        "BRAINSOS_OWNER_ONLY": "true",
        "AUTH_COGNITO_ADMIN_GROUP": "brainsos-admins",
    }

    res = authenticate_alb_headers(
        {"X-Amzn-Oidc-Data": token},
        env,
        key_fetcher=lambda _r, _k: pub_pem,
    )
    assert res["is_admin"] is True
    assert res["is_group_admin"] is True
    assert res["headers"]["X-Authentik-Groups"] == "authentik Admins"


def test_alb_jwt_rejects_expired_bad_sig_wrong_signer_and_ssrf_kid():
    """Verify strict ES256, exp, signer ARN, and SSRF-safe kid validation."""
    priv, pub_pem = _make_ec_keypair()
    other_priv, other_pub_pem = _make_ec_keypair()
    env = {
        "AUTH_ALB_OIDC_ENABLED": "true",
        "AUTH_ALB_SIGNER_ARN": SAMPLE_SIGNER_ARN,
        "BRAINSOS_USER_SUB": "owner-sub",
    }

    # 1. Expired JWT
    expired = _sign_alb_jwt(priv, {"sub": "owner-sub", "exp": int(time.time()) - 120})
    with pytest.raises(AlbAuthError) as e1:
        authenticate_alb_headers({"X-Amzn-Oidc-Data": expired}, env, key_fetcher=lambda _r, _k: pub_pem)
    assert e1.value.status_code == 401

    # 2. Invalid signature (signed with wrong private key)
    bad_sig = _sign_alb_jwt(other_priv, {"sub": "owner-sub", "exp": int(time.time()) + 300})
    with pytest.raises(AlbAuthError) as e2:
        authenticate_alb_headers({"X-Amzn-Oidc-Data": bad_sig}, env, key_fetcher=lambda _r, _k: pub_pem)
    assert e2.value.status_code == 401

    # 3. Wrong signer ARN
    wrong_signer = _sign_alb_jwt(
        other_priv,
        {"sub": "owner-sub", "exp": int(time.time()) + 300},
        signer="arn:aws:elasticloadbalancing:us-east-1:999999999999:loadbalancer/app/evil/deadbeef",
    )
    with pytest.raises(AlbAuthError) as e3:
        authenticate_alb_headers(
            {"X-Amzn-Oidc-Data": wrong_signer},
            env,
            key_fetcher=lambda _r, _k: other_pub_pem,
        )
    assert e3.value.status_code == 403

    # 4. SSRF / path traversal kid must never invoke key_fetcher
    called = []
    ssrf_tok = _sign_alb_jwt(
        priv,
        {"sub": "owner-sub", "exp": int(time.time()) + 300},
        kid="../../169.254.169.254/latest",
    )
    with pytest.raises(AlbAuthError) as e4:
        authenticate_alb_headers(
            {"X-Amzn-Oidc-Data": ssrf_tok},
            env,
            key_fetcher=lambda r, k: (called.append((r, k)), pub_pem)[1],  # type: ignore[func-returns-value]
        )
    assert e4.value.status_code == 401
    assert called == []

    # 5. Disabled ALB mode fails closed
    disabled_tok = _sign_alb_jwt(priv, {"sub": "owner-sub", "exp": int(time.time()) + 300})
    with pytest.raises(AlbAuthError) as e5:
        authenticate_alb_headers(
            {"X-Amzn-Oidc-Data": disabled_tok},
            {**env, "AUTH_ALB_OIDC_ENABLED": "false"},
            key_fetcher=lambda _r, _k: pub_pem,
        )
    assert e5.value.status_code == 401


def test_alb_verify_endpoint_roundtrip(tmp_path):
    """Test /api/v1/system/auth/alb-verify forward-auth response headers."""
    priv, pub_pem = _make_ec_keypair()
    (tmp_path / ".env").write_text(
        f"BRAINSOS_DOMAIN=box.brainsos.ai\n"
        f"AUTH_ALB_OIDC_ENABLED=true\n"
        f"AUTH_ALB_SIGNER_ARN={SAMPLE_SIGNER_ARN}\n"
        f"BRAINSOS_USER_SUB=ebs-owner-uuid\n"
        f"BRAINSOS_OWNER_ONLY=true\n",
        encoding="utf-8",
    )
    token = _sign_alb_jwt(
        priv,
        {
            "sub": "ebs-owner-uuid",
            "preferred_username": "owner_u",
            "email": "owner@example.com",
            "exp": int(time.time()) + 300,
        },
    )

    with (
        patch("brainsos_telemetry.system.get_repo_root", return_value=str(tmp_path)),
        patch("brainsos_telemetry.alb_auth.fetch_alb_public_key", return_value=pub_pem),
    ):
        app = create_system_api_app()
        client = TestClient(app)

        res = client.get(
            "/api/v1/system/auth/alb-verify",
            headers={
                "X-BrainsOS-Internal": "test-secret-token-12345",
                "X-Amzn-Oidc-Data": token,
            },
        )
        assert res.status_code == 200
        assert res.headers["X-Authentik-Groups"] == "authentik Admins"
        assert res.headers["X-BrainsOS-Owner"] == "true"
        assert res.headers["X-Authentik-Username"] == "owner_u"
        assert res.headers["X-Authentik-Uid"] == "ebs-owner-uuid"


def test_breakglass_toggle_api_and_lockout_prevention(tmp_path, monkeypatch):
    """Verify break-glass toggle refuses lockout and persists safely when superuser/SSO exists."""
    monkeypatch.setenv("BRAINSOS_TEST_INSTANCE_ID", "i-0123456789abcdef0")
    (tmp_path / ".env").write_text(
        "BRAINSOS_DOMAIN=box.brainsos.ai\n"
        "BRAINSOS_ADMIN_USERNAME=admin\n"
        "BRAINSOS_BREAKGLASS_ENABLED=true\n",
        encoding="utf-8",
    )

    assert validate_breakglass_toggle(False, {"BRAINSOS_ADMIN_USERNAME": "admin"}) is not None
    assert validate_breakglass_toggle(False, {"BRAINSOS_SUPERUSER_USERNAME": "jsm"}) is None
    assert (
        validate_breakglass_toggle(
            False,
            {"BRAINSOS_USER_SUB": "sub-1", "AUTH_COGNITO_ENABLED": "true"},
        )
        is None
    )

    with patch("brainsos_telemetry.system.get_repo_root", return_value=str(tmp_path)):
        app = create_system_api_app()
        client = TestClient(app)
        csrf = issue_csrf_token()
        admin_headers = {
            "X-BrainsOS-Internal": "test-secret-token-12345",
            "X-Authentik-Username": "admin",
            "X-Authentik-Groups": "authentik Admins",
            "X-CSRF-Token": csrf,
            "Origin": "https://box.brainsos.ai",
        }

        # Non-admin denied
        viewer_res = client.get(
            "/api/v1/system/security/breakglass",
            headers={
                "X-BrainsOS-Internal": "test-secret-token-12345",
                "X-Authentik-Username": "viewer",
                "X-Authentik-Groups": "brainsos-viewers",
            },
        )
        assert viewer_res.status_code == 403

        # Lockout refused when no named superuser or Cognito owner exists
        blocked = client.post(
            "/api/v1/system/security/breakglass",
            json={"enabled": False, "apply_now": False},
            headers=admin_headers,
        )
        assert blocked.status_code == 400

        # Add named superuser -> disabling break-glass succeeds
        (tmp_path / ".env").write_text(
            (tmp_path / ".env").read_text(encoding="utf-8") + "BRAINSOS_SUPERUSER_USERNAME=jsm\n",
            encoding="utf-8",
        )
        off_res = client.post(
            "/api/v1/system/security/breakglass",
            json={"enabled": False, "apply_now": False},
            headers=admin_headers,
        )
        assert off_res.status_code == 200
        assert off_res.json()["breakglass_enabled"] is False
        assert "BRAINSOS_BREAKGLASS_ENABLED=false" in (tmp_path / ".env").read_text(encoding="utf-8")

        get_res = client.get("/api/v1/system/security/breakglass", headers=admin_headers)
        assert get_res.status_code == 200
        assert get_res.json()["breakglass_enabled"] is False
        assert get_res.json()["can_disable"] is True


def test_cognito_sso_config_api_masks_secret_and_derives_callback(tmp_path):
    """Verify /api/v1/system/sso/cognito validates inputs, hides secrets, and returns callback URI."""
    (tmp_path / ".env").write_text("BRAINSOS_DOMAIN=demo.brainsos.ai\n", encoding="utf-8")

    with patch("brainsos_telemetry.system.get_repo_root", return_value=str(tmp_path)):
        app = create_system_api_app()
        client = TestClient(app)
        csrf = issue_csrf_token()
        admin_headers = {
            "X-BrainsOS-Internal": "test-secret-token-12345",
            "X-Authentik-Username": "su",
            "X-Authentik-Groups": "authentik Admins",
            "X-CSRF-Token": csrf,
            "Origin": "https://demo.brainsos.ai",
        }

        post_res = client.post(
            "/api/v1/system/sso/cognito",
            json={
                "enabled": True,
                "region": "us-east-1",
                "user_pool_id": "us-east-1_AbCdEf123",
                "client_id": "app-client-123",
                "client_secret": "super-secret-cognito-val",
                "alb_oidc_enabled": True,
                "alb_signer_arn": SAMPLE_SIGNER_ARN,
                "user_sub": "user-sub-777",
                "owner_only": True,
                "reload_sso": False,
            },
            headers=admin_headers,
        )
        assert post_res.status_code == 200
        assert post_res.json()["redirect_uri"] == "https://demo.brainsos.ai/source/oauth/callback/cognito/"

        get_res = client.get("/api/v1/system/sso/cognito", headers=admin_headers)
        assert get_res.status_code == 200
        data = get_res.json()
        assert data["cognito_enabled"] is True
        assert data["client_secret_configured"] is True
        assert data["user_sub"] == "user-sub-777"
        assert "super-secret-cognito-val" not in get_res.text

        # Invalid ARN must be rejected cleanly
        bad_arn = client.post(
            "/api/v1/system/sso/cognito",
            json={"alb_signer_arn": "not-an-arn", "reload_sso": False},
            headers=admin_headers,
        )
        assert bad_arn.status_code == 400


def test_rbac_redirect_and_script_hardening_invariants():
    """Verify HIGH-02/HIGH-03/MED-04/MED-05 security invariants in config & scripts."""
    blueprint = (REPO_ROOT / "config/authentik/blueprints/brainsos-portal.yaml").read_text(encoding="utf-8")
    assert not re.search(r"(?m)^\s*\.\*\s*$", blueprint)
    assert "https://.*" not in blueprint
    assert "http://.*" not in blueprint

    reload_sh = (REPO_ROOT / "scripts/control/reload-env.sh").read_text(encoding="utf-8")
    assert r"\n.*" not in reload_sh
    assert "OAuthSource.objects.get_or_create" in reload_sh

    portal_sh = (REPO_ROOT / "scripts/setup/setup-portal.sh").read_text(encoding="utf-8")
    assert r"\n.*" not in portal_sh
    assert "AUTHENTIK_OPERATOR_PASSWORD:-brainsos" not in portal_sh

    compose_ctrl = (REPO_ROOT / "docker/compose/compose.control.yml").read_text(encoding="utf-8")
    assert "GENERIC_ROLE_MAPPINGS_DEFAULT_ROLE=${AUTH_LITELLM_DEFAULT_ROLE:-internal_user_viewer}" in compose_ctrl

    litellm_sh = (REPO_ROOT / "scripts/setup/setup-litellm-sso.sh").read_text(encoding="utf-8")
    assert "SwZjRtnmaNCxBrgkX2VX6X7M" not in litellm_sh
    assert "a6cfd544eb4907689db9d97002fc4f7beaa1edcd7b2f9abad21ea1008b6933f5" not in litellm_sh
    assert 'LITELLM_DEFAULT_ROLE="${AUTH_LITELLM_DEFAULT_ROLE:-internal_user_viewer}"' in litellm_sh

    git_sh = (REPO_ROOT / "scripts/setup/setup-git.sh").read_text(encoding="utf-8")
    assert "chmod 664" not in git_sh
    assert 'chmod 600 "${CRED_FILE}"' in git_sh

    langfuse_sh = (REPO_ROOT / "scripts/setup/setup-langfuse.sh").read_text(encoding="utf-8")
    assert 'chmod 600 "${LANGFUSE_ENV_FILE}"' in langfuse_sh
    assert "brainsos_is_authorized_admin_email" in langfuse_sh
    assert "v_org_role := 'VIEWER'" in langfuse_sh
