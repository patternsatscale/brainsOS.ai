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
    is_valid_https_issuer,
    validate_breakglass_toggle,
    verify_alb_oidc_jwt,
)
from brainsos_telemetry.system import create_system_api_app, issue_csrf_token
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[3]
SAMPLE_SIGNER_ARN = (
    "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/brainsos-alb/0123456789abcdef"
)
SAMPLE_ALB_ISSUER = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_AbCdEf123"
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
    for var in ("BRAINSOS_URL", "BRAINSOS_DOMAIN", "BRAINSOS_LOCAL_DOMAIN", "BRAINSOS_USER_SUB"):
        monkeypatch.delenv(var, raising=False)
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
            "iss": SAMPLE_ALB_ISSUER,
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
        "AUTH_ALB_ISSUER": SAMPLE_ALB_ISSUER,
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
            "iss": SAMPLE_ALB_ISSUER,
            "preferred_username": "bob",
            "email": "bob@example.com",
            "exp": int(time.time()) + 300,
        },
    )
    base_env = {
        "AUTH_ALB_OIDC_ENABLED": "true",
        "AUTH_ALB_SIGNER_ARN": SAMPLE_SIGNER_ARN,
        "AUTH_ALB_ISSUER": SAMPLE_ALB_ISSUER,
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
            "iss": SAMPLE_ALB_ISSUER,
            "email": "ops@example.com",
            "cognito:groups": ["brainsos-admins"],
            "exp": int(time.time()) + 300,
        },
    )
    env = {
        "AUTH_ALB_OIDC_ENABLED": "true",
        "AUTH_ALB_SIGNER_ARN": SAMPLE_SIGNER_ARN,
        "AUTH_ALB_ISSUER": SAMPLE_ALB_ISSUER,
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
        "AUTH_ALB_ISSUER": SAMPLE_ALB_ISSUER,
        "BRAINSOS_USER_SUB": "owner-sub",
    }

    # 1. Expired JWT
    expired = _sign_alb_jwt(priv, {"sub": "owner-sub", "iss": SAMPLE_ALB_ISSUER, "exp": int(time.time()) - 120})
    with pytest.raises(AlbAuthError) as e1:
        authenticate_alb_headers({"X-Amzn-Oidc-Data": expired}, env, key_fetcher=lambda _r, _k: pub_pem)
    assert e1.value.status_code == 401

    # 2. Invalid signature (signed with wrong private key)
    bad_sig = _sign_alb_jwt(other_priv, {"sub": "owner-sub", "iss": SAMPLE_ALB_ISSUER, "exp": int(time.time()) + 300})
    with pytest.raises(AlbAuthError) as e2:
        authenticate_alb_headers({"X-Amzn-Oidc-Data": bad_sig}, env, key_fetcher=lambda _r, _k: pub_pem)
    assert e2.value.status_code == 401

    # 3. Wrong signer ARN
    wrong_signer = _sign_alb_jwt(
        other_priv,
        {"sub": "owner-sub", "iss": SAMPLE_ALB_ISSUER, "exp": int(time.time()) + 300},
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
        {"sub": "owner-sub", "iss": SAMPLE_ALB_ISSUER, "exp": int(time.time()) + 300},
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
    disabled_tok = _sign_alb_jwt(priv, {"sub": "owner-sub", "iss": SAMPLE_ALB_ISSUER, "exp": int(time.time()) + 300})
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
        f"AUTH_ALB_ISSUER={SAMPLE_ALB_ISSUER}\n"
        f"BRAINSOS_USER_SUB=ebs-owner-uuid\n"
        f"BRAINSOS_OWNER_ONLY=true\n",
        encoding="utf-8",
    )
    token = _sign_alb_jwt(
        priv,
        {
            "sub": "ebs-owner-uuid",
            "iss": SAMPLE_ALB_ISSUER,
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
                "alb_issuer": SAMPLE_ALB_ISSUER,
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
        assert data["alb_issuer"] == SAMPLE_ALB_ISSUER
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


def test_setup_endpoint_passes_breakglass_and_cognito_flags(tmp_path, monkeypatch):
    """Verify POST /api/v1/system/setup propagates wizard break-glass and Cognito options (#386)."""
    mock_iid = "i-0" + ("c" * 16)
    monkeypatch.setenv("BRAINSOS_TEST_INSTANCE_ID", mock_iid)
    (tmp_path / ".env").write_text(
        f"BRAINSOS_DOMAIN=box.brainsos.ai\nBRAINSOS_INSTANCE_ID={mock_iid}\nBRAINSOS_WIZARD_COMPLETED=false\n",
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
            "X-CSRF-Token": csrf_tok,
            "Origin": "https://box.brainsos.ai",
        }
        res = client.post(
            "/api/v1/system/setup",
            json={
                "bootstrap_token": mock_iid,
                "unit_name": "Alice Agent Box",
                "superuser_name": "Alice Operator",
                "superuser_username": "alice",
                "superuser_password": "StrongUserPass99!",
                "local_domain": "alice.aws.cloud.brainsos.ai",
                "url": "box.brainsos.ai",
                "tls_mode": "internal",
                "breakglass_enabled": False,
                "cognito_enabled": True,
                "cognito_region": "us-east-1",
                "cognito_user_pool_id": "us-east-1_TestPool1",
                "cognito_client_id": "client-xyz",
                "cognito_client_secret": "SecretFromWizard123!",
                "alb_oidc_enabled": True,
                "alb_signer_arn": SAMPLE_SIGNER_ARN,
                "alb_issuer": SAMPLE_ALB_ISSUER,
                "user_sub": "owner-sub-xyz",
                "owner_only": True,
            },
            headers=headers,
        )
        assert res.status_code == 200
        assert "--no-breakglass" in res.text
        assert "--cognito-enabled" in res.text
        assert "--cognito-region us-east-1" in res.text
        assert "--cognito-pool-id us-east-1_TestPool1" in res.text
        assert "--alb-oidc" in res.text
        assert f"--alb-issuer {SAMPLE_ALB_ISSUER}" in res.text
        assert "--user-sub owner-sub-xyz" in res.text
        assert "SecretFromWizard123!" not in res.text


def test_alb_jwt_fails_closed_when_signer_or_issuer_empty_or_account_mismatch():
    """verify_alb_oidc_jwt must fail closed (403) when signer/issuer allowlists are empty or account mismatches."""
    priv, pub_pem = _make_ec_keypair()
    token = _sign_alb_jwt(
        priv,
        {
            "sub": "owner-sub",
            "iss": SAMPLE_ALB_ISSUER,
            "exp": int(time.time()) + 300,
        },
    )

    fetched = []

    def tracking_fetcher(region: str, kid: str) -> str:
        fetched.append((region, kid))
        return pub_pem

    # 1. Empty / missing / comma-only AUTH_ALB_SIGNER_ARN
    for bad_signer in ("", "   ", " , "):
        with pytest.raises(AlbAuthError) as exc:
            authenticate_alb_headers(
                {"X-Amzn-Oidc-Data": token},
                {
                    "AUTH_ALB_OIDC_ENABLED": "true",
                    "AUTH_ALB_SIGNER_ARN": bad_signer,
                    "AUTH_ALB_ISSUER": SAMPLE_ALB_ISSUER,
                    "BRAINSOS_USER_SUB": "owner-sub",
                },
                key_fetcher=tracking_fetcher,
            )
        assert exc.value.status_code == 403
        assert fetched == []

    # 2. Empty / missing / non-https AUTH_ALB_ISSUER
    for bad_issuer in ("", "   ", "http://cognito-idp.us-east-1.amazonaws.com/pool"):
        with pytest.raises(AlbAuthError) as exc:
            authenticate_alb_headers(
                {"X-Amzn-Oidc-Data": token},
                {
                    "AUTH_ALB_OIDC_ENABLED": "true",
                    "AUTH_ALB_SIGNER_ARN": SAMPLE_SIGNER_ARN,
                    "AUTH_ALB_ISSUER": bad_issuer,
                    "BRAINSOS_USER_SUB": "owner-sub",
                },
                key_fetcher=tracking_fetcher,
            )
        assert exc.value.status_code == 403
        assert fetched == []

    # 3. Mismatched AUTH_ALB_AWS_ACCOUNT
    with pytest.raises(AlbAuthError) as exc_acc:
        authenticate_alb_headers(
            {"X-Amzn-Oidc-Data": token},
            {
                "AUTH_ALB_OIDC_ENABLED": "true",
                "AUTH_ALB_SIGNER_ARN": SAMPLE_SIGNER_ARN,
                "AUTH_ALB_ISSUER": SAMPLE_ALB_ISSUER,
                "AUTH_ALB_AWS_ACCOUNT": "999999999999",
                "BRAINSOS_USER_SUB": "owner-sub",
            },
            key_fetcher=tracking_fetcher,
        )
    assert exc_acc.value.status_code == 403
    assert fetched == []

    # 4. Matching AUTH_ALB_AWS_ACCOUNT succeeds
    ok = authenticate_alb_headers(
        {"X-Amzn-Oidc-Data": token},
        {
            "AUTH_ALB_OIDC_ENABLED": "true",
            "AUTH_ALB_SIGNER_ARN": SAMPLE_SIGNER_ARN,
            "AUTH_ALB_ISSUER": SAMPLE_ALB_ISSUER,
            "AUTH_ALB_AWS_ACCOUNT": "123456789012",
            "BRAINSOS_USER_SUB": "owner-sub",
        },
        key_fetcher=tracking_fetcher,
    )
    assert ok["is_owner"] is True
    assert len(fetched) == 1


def test_alb_oidc_config_and_forward_auth_reject_missing_signer_or_issuer_400(tmp_path, monkeypatch):
    """update_cognito_sso_config, verify_alb_forward_auth, and trigger_setup return 400 without valid signer & https issuer."""
    mock_iid = "i-0" + ("d" * 16)
    monkeypatch.setenv("BRAINSOS_TEST_INSTANCE_ID", mock_iid)
    (tmp_path / ".env").write_text(
        f"BRAINSOS_DOMAIN=box.brainsos.ai\nBRAINSOS_INSTANCE_ID={mock_iid}\nBRAINSOS_WIZARD_COMPLETED=false\n",
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
        admin_headers = {
            "X-BrainsOS-Internal": "test-secret-token-12345",
            "X-Authentik-Username": "su",
            "X-Authentik-Groups": "authentik Admins",
            "X-CSRF-Token": csrf_tok,
            "Origin": "https://box.brainsos.ai",
        }

        # 1. update_cognito_sso_config rejects alb_oidc_enabled=True without signer or https issuer
        r1 = client.post(
            "/api/v1/system/sso/cognito",
            json={"alb_oidc_enabled": True, "alb_signer_arn": SAMPLE_SIGNER_ARN, "reload_sso": False},
            headers=admin_headers,
        )
        assert r1.status_code == 400

        r2 = client.post(
            "/api/v1/system/sso/cognito",
            json={
                "alb_oidc_enabled": True,
                "alb_signer_arn": SAMPLE_SIGNER_ARN,
                "alb_issuer": "http://insecure.example.com",
                "reload_sso": False,
            },
            headers=admin_headers,
        )
        assert r2.status_code == 400

        r3 = client.post(
            "/api/v1/system/sso/cognito",
            json={"alb_oidc_enabled": True, "alb_issuer": SAMPLE_ALB_ISSUER, "reload_sso": False},
            headers=admin_headers,
        )
        assert r3.status_code == 400

        # 2. trigger_setup rejects alb_oidc_enabled=True without signer or https issuer
        r4 = client.post(
            "/api/v1/system/setup",
            json={
                "bootstrap_token": mock_iid,
                "alb_oidc_enabled": True,
                "alb_signer_arn": SAMPLE_SIGNER_ARN,
            },
            headers={
                "X-BrainsOS-Internal": "test-secret-token-12345",
                "X-CSRF-Token": csrf_tok,
                "Origin": "https://box.brainsos.ai",
            },
        )
        assert r4.status_code == 400

        # 3. verify_alb_forward_auth returns 400 when AUTH_ALB_OIDC_ENABLED=true without valid signer/issuer
        (tmp_path / ".env").write_text(
            "BRAINSOS_DOMAIN=box.brainsos.ai\nAUTH_ALB_OIDC_ENABLED=true\n",
            encoding="utf-8",
        )
        r5 = client.get(
            "/api/v1/system/auth/alb-verify",
            headers={"X-BrainsOS-Internal": "test-secret-token-12345"},
        )
        assert r5.status_code == 400


def test_breakglass_auto_disabled_on_wizard_and_cognito_unless_explicitly_reenabled(tmp_path, monkeypatch):
    """Break-glass auto-disables on wizard credential setup or Cognito SSO unless admin explicitly re-enables."""
    mock_iid = "i-0" + ("e" * 16)
    monkeypatch.setenv("BRAINSOS_TEST_INSTANCE_ID", mock_iid)
    (tmp_path / ".env").write_text(
        f"BRAINSOS_DOMAIN=box.brainsos.ai\n"
        f"BRAINSOS_INSTANCE_ID={mock_iid}\n"
        f"BRAINSOS_WIZARD_COMPLETED=false\n"
        f"BRAINSOS_BREAKGLASS_ENABLED=true\n",
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

        # 1. Wizard setup without breakglass_enabled auto-passes --no-breakglass & persists false
        wiz_res = client.post(
            "/api/v1/system/setup",
            json={
                "bootstrap_token": mock_iid,
                "unit_name": "Alice Agent Box",
                "superuser_name": "Alice Operator",
                "superuser_username": "alice",
                "superuser_password": "StrongUserPass99!",
                "local_domain": "alice.aws.cloud.brainsos.ai",
                "url": "box.brainsos.ai",
                "tls_mode": "internal",
            },
            headers={
                "X-BrainsOS-Internal": "test-secret-token-12345",
                "X-CSRF-Token": csrf_tok,
                "Origin": "https://box.brainsos.ai",
            },
        )
        assert wiz_res.status_code == 200
        assert "--no-breakglass" in wiz_res.text
        assert "BRAINSOS_BREAKGLASS_ENABLED=false" in (tmp_path / ".env").read_text(encoding="utf-8")

        # 2. Reset breakglass to default true (non-explicit) and enable Cognito SSO -> auto-disables breakglass
        (tmp_path / ".env").write_text(
            f"BRAINSOS_DOMAIN=box.brainsos.ai\n"
            f"BRAINSOS_INSTANCE_ID={mock_iid}\n"
            f"BRAINSOS_WIZARD_COMPLETED=true\n"
            f"BRAINSOS_BREAKGLASS_ENABLED=true\n",
            encoding="utf-8",
        )
        admin_headers = {
            "X-BrainsOS-Internal": "test-secret-token-12345",
            "X-Authentik-Username": "su",
            "X-Authentik-Groups": "authentik Admins",
            "X-CSRF-Token": csrf_tok,
            "Origin": "https://box.brainsos.ai",
        }
        cog_res = client.post(
            "/api/v1/system/sso/cognito",
            json={
                "enabled": True,
                "region": "us-east-1",
                "user_pool_id": "us-east-1_AbCdEf123",
                "client_id": "app-client-123",
                "user_sub": "owner-sub-1",
                "reload_sso": False,
            },
            headers=admin_headers,
        )
        assert cog_res.status_code == 200
        assert "BRAINSOS_BREAKGLASS_ENABLED=false" in (tmp_path / ".env").read_text(encoding="utf-8")

        # 3. Admin explicitly re-enables breakglass -> subsequent Cognito update preserves breakglass=true
        bg_on = client.post(
            "/api/v1/system/security/breakglass",
            json={"enabled": True, "apply_now": False},
            headers=admin_headers,
        )
        assert bg_on.status_code == 200
        cog_res2 = client.post(
            "/api/v1/system/sso/cognito",
            json={"owner_only": False, "reload_sso": False},
            headers=admin_headers,
        )
        assert cog_res2.status_code == 200
        assert "BRAINSOS_BREAKGLASS_ENABLED=true" in (tmp_path / ".env").read_text(encoding="utf-8")


def test_is_valid_https_issuer_and_endpoints_reject_malformed_urls_without_500(tmp_path, monkeypatch):
    """Malformed URLs must return False / AlbAuthError(403) / HTTP 400 and never raise ValueError / HTTP 500."""
    bad_issuers = (
        "https://[",
        "https://]",
        "https://[::1",
        "https://[invalid]",
        "https://host:99999",
        "https://host:abc",
        "https://:443/path",
        "https://host with space.com",
        "https://",
        "https:///path",
        "http://example.com",
    )
    for val in bad_issuers:
        assert is_valid_https_issuer(val) is False, f"Expected False for {val!r}"

    for valid_val in ("https://[::1]", "https://example.com:8443/issuer", SAMPLE_ALB_ISSUER):
        assert is_valid_https_issuer(valid_val) is True, f"Expected True for {valid_val!r}"

    priv, pub_pem = _make_ec_keypair()
    token = _sign_alb_jwt(
        priv,
        {
            "sub": "owner-sub",
            "iss": SAMPLE_ALB_ISSUER,
            "exp": int(time.time()) + 300,
        },
    )
    fetched = []

    def tracking_fetcher(region: str, kid: str) -> str:
        fetched.append((region, kid))
        return pub_pem

    for bad_issuer in (
        "https://[",
        "https://]",
        "https://[::1",
        "https://[invalid]",
        "https://host:99999",
        "https://host:abc",
        "https://:443/path",
        "https://host with space.com",
    ):
        with pytest.raises(AlbAuthError) as exc_info:
            verify_alb_oidc_jwt(
                token,
                {
                    "AUTH_ALB_OIDC_ENABLED": "true",
                    "AUTH_ALB_SIGNER_ARN": SAMPLE_SIGNER_ARN,
                    "AUTH_ALB_ISSUER": bad_issuer,
                    "BRAINSOS_USER_SUB": "owner-sub",
                },
                key_fetcher=tracking_fetcher,
            )
        assert exc_info.value.status_code == 403
        assert fetched == []

    mock_iid = "i-0" + ("f" * 16)
    monkeypatch.setenv("BRAINSOS_TEST_INSTANCE_ID", mock_iid)
    (tmp_path / ".env").write_text(
        f"BRAINSOS_DOMAIN=box.brainsos.ai\nBRAINSOS_INSTANCE_ID={mock_iid}\nBRAINSOS_WIZARD_COMPLETED=false\n",
        encoding="utf-8",
    )
    script_dir = tmp_path / "scripts" / "control"
    script_dir.mkdir(parents=True)
    set_domain_sh = script_dir / "set-domain.sh"
    set_domain_sh.write_text('#!/usr/bin/env bash\necho "SETUP_ARGS: $*"\n', encoding="utf-8")
    set_domain_sh.chmod(0o755)

    with patch("brainsos_telemetry.system.get_repo_root", return_value=str(tmp_path)):
        app = create_system_api_app()
        client = TestClient(app, raise_server_exceptions=False)
        csrf_tok = issue_csrf_token()
        admin_headers = {
            "X-BrainsOS-Internal": "test-secret-token-12345",
            "X-Authentik-Username": "su",
            "X-Authentik-Groups": "authentik Admins",
            "X-CSRF-Token": csrf_tok,
            "Origin": "https://box.brainsos.ai",
        }
        setup_headers = {
            "X-BrainsOS-Internal": "test-secret-token-12345",
            "X-CSRF-Token": csrf_tok,
            "Origin": "https://box.brainsos.ai",
        }

        for bad_issuer in ("https://[", "https://]", "https://host:99999", "https://:443/path"):
            (tmp_path / ".env").write_text(
                f"BRAINSOS_DOMAIN=box.brainsos.ai\nBRAINSOS_INSTANCE_ID={mock_iid}\nBRAINSOS_WIZARD_COMPLETED=false\n",
                encoding="utf-8",
            )
            r_cog = client.post(
                "/api/v1/system/sso/cognito",
                json={
                    "alb_oidc_enabled": True,
                    "alb_signer_arn": SAMPLE_SIGNER_ARN,
                    "alb_issuer": bad_issuer,
                    "reload_sso": False,
                },
                headers=admin_headers,
            )
            assert r_cog.status_code == 400

            r_setup = client.post(
                "/api/v1/system/setup",
                json={
                    "bootstrap_token": mock_iid,
                    "alb_oidc_enabled": True,
                    "alb_signer_arn": SAMPLE_SIGNER_ARN,
                    "alb_issuer": bad_issuer,
                },
                headers=setup_headers,
            )
            assert r_setup.status_code == 400

            (tmp_path / ".env").write_text(
                f"BRAINSOS_DOMAIN=box.brainsos.ai\n"
                f"AUTH_ALB_OIDC_ENABLED=true\n"
                f"AUTH_ALB_SIGNER_ARN={SAMPLE_SIGNER_ARN}\n"
                f"AUTH_ALB_ISSUER={bad_issuer}\n",
                encoding="utf-8",
            )
            r_verify = client.get(
                "/api/v1/system/auth/alb-verify",
                headers={
                    "X-BrainsOS-Internal": "test-secret-token-12345",
                    "X-Amzn-Oidc-Data": token,
                },
            )
            assert r_verify.status_code == 400


def test_compose_ingress_forwards_auth_alb_trusted_cidrs():
    """Verify docker/compose/compose.ingress.yml forwards AUTH_ALB_TRUSTED_CIDRS with RFC1918 defaults."""
    compose_ingress = (REPO_ROOT / "docker/compose/compose.ingress.yml").read_text(encoding="utf-8")
    assert "AUTH_ALB_TRUSTED_CIDRS=${AUTH_ALB_TRUSTED_CIDRS:-10.0.0.0/8 172.16.0.0/12 192.168.0.0/16}" in (
        compose_ingress
    )


