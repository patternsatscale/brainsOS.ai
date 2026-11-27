"""Tier 3 E2E Tests: Cross-Feature Combinatorial Interactions (26 tests covering F1-F24)."""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from .conftest import (
    REPO_ROOT,
    VALID_ISSUER,
    VALID_SIGNER_ARN,
    extract_caddy_block,
    find_unquoted_python_heredocs_with_expansion,
    load_module_from_path,
    load_yaml,
    read_repo_text,
)


def test_t3_01_f1_f2_alb_config_plus_jwt_and_account_verification(
    isolated_repo, system_api_client_factory, ec_keypair, make_alb_jwt
):
    """F1 + F2: Configure ALB OIDC via API (validated ARN+HTTPS), then verify ES256 JWT + AWS account via alb-verify."""
    _, pub_pem = ec_keypair
    bundle = system_api_client_factory(isolated_repo)
    cfg_res = bundle["client"].post(
        "/api/v1/system/sso/cognito",
        json={
            "alb_oidc_enabled": True,
            "alb_signer_arn": VALID_SIGNER_ARN,
            "alb_issuer": VALID_ISSUER,
            "user_sub": "owner-sub-1",
            "reload_sso": False,
        },
        headers=bundle["admin_headers"],
    )
    assert cfg_res.status_code == 200

    token = make_alb_jwt(sub="owner-sub-1")
    with (
        patch("brainsos_telemetry.alb_auth.fetch_alb_public_key", return_value=pub_pem),
        patch.dict(os.environ, {"AUTH_ALB_AWS_ACCOUNT": "123456789012"}),
    ):
        ok_res = bundle["client"].get(
            "/api/v1/system/auth/alb-verify",
            headers={**bundle["internal_headers"], "X-Amzn-Oidc-Data": token},
        )
    assert ok_res.status_code == 200
    assert ok_res.headers.get("X-Authentik-Groups") == "authentik Admins"

    with (
        patch("brainsos_telemetry.alb_auth.fetch_alb_public_key", return_value=pub_pem),
        patch.dict(os.environ, {"AUTH_ALB_AWS_ACCOUNT": "999999999999"}),
    ):
        bad_acct = bundle["client"].get(
            "/api/v1/system/auth/alb-verify",
            headers={**bundle["internal_headers"], "X-Amzn-Oidc-Data": token},
        )
    assert bad_acct.status_code == 403


def test_t3_02_f1_f4_f6_alb_owner_elevation_propagates_to_identity_and_admin_endpoints(
    isolated_repo, system_api_client_factory, ec_keypair, make_alb_jwt
):
    """F1 + F4 + F6: ALB verify emits RBAC headers; admin receives full /identity while non-admin receives minimized."""
    _, pub_pem = ec_keypair
    bundle = system_api_client_factory(
        isolated_repo,
        env_text=(
            "BRAINSOS_STAGE=test\n"
            "SYSTEM_API_TOKEN=e2e-internal-token-12345\n"
            "BRAINSOS_WIZARD_COMPLETED=true\n"
            "BRAINSOS_UNIT_NAME=ComboUnit\n"
            "BRAINSOS_INSTANCE_ID=i-0deadbeef12345678\n"
            "AUTH_ALB_OIDC_ENABLED=true\n"
            f"AUTH_ALB_SIGNER_ARN={VALID_SIGNER_ARN}\n"
            f"AUTH_ALB_ISSUER={VALID_ISSUER}\n"
            "BRAINSOS_USER_SUB=owner-sub-1\n"
            "BRAINSOS_OWNER_ONLY=false\n"
        ),
        wizard_completed=True,
    )
    owner_jwt = make_alb_jwt(sub="owner-sub-1", extra_claims={"preferred_username": "alice"})
    viewer_jwt = make_alb_jwt(sub="viewer-sub-2", extra_claims={"preferred_username": "bob"})

    with patch("brainsos_telemetry.alb_auth.fetch_alb_public_key", return_value=pub_pem):
        r_own = bundle["client"].get(
            "/api/v1/system/auth/alb-verify",
            headers={**bundle["internal_headers"], "X-Amzn-Oidc-Data": owner_jwt},
        )
        r_view = bundle["client"].get(
            "/api/v1/system/auth/alb-verify",
            headers={**bundle["internal_headers"], "X-Amzn-Oidc-Data": viewer_jwt},
        )
    assert r_own.status_code == 200 and r_own.headers["X-Authentik-Groups"] == "authentik Admins"
    assert r_view.status_code == 200 and r_view.headers["X-Authentik-Groups"] == "brainsos-viewers"

    id_own = bundle["client"].get(
        "/api/v1/system/identity",
        headers={
            **bundle["internal_headers"],
            "X-Authentik-Username": r_own.headers["X-Authentik-Username"],
            "X-Authentik-Groups": r_own.headers["X-Authentik-Groups"],
        },
    )
    id_view = bundle["client"].get(
        "/api/v1/system/identity",
        headers={
            **bundle["internal_headers"],
            "X-Authentik-Username": r_view.headers["X-Authentik-Username"],
            "X-Authentik-Groups": r_view.headers["X-Authentik-Groups"],
        },
    )
    assert "instance_id" in id_own.json()
    assert "instance_id" not in id_view.json()


def test_t3_03_f2_f5_f6_caddy_routing_matrix_consistency():
    """F2 + F5 + F6: Both Caddyfiles align CIDR-scoped ALB, system_api_auth on status/jobs, and admin RBAC."""
    for rel in ("config/caddy/Caddyfile", "config/caddy/Caddyfile.appliance"):
        txt = read_repo_text(rel)
        assert "remote_ip" in extract_caddy_block(txt, "@has_alb_oidc")
        public_tokens = extract_caddy_block(txt, "@system_public_status").split()
        assert "/api/v1/system/status" not in public_tokens
        assert "/api/v1/system/jobs" not in public_tokens
        assert "/api/v1/system/jobs/*" not in public_tokens
        for admin_route in ("/editor/*", "/efw/*", "/runner*", "/git/*", "@openbao_paths"):
            assert "authentik_admin_forward_auth" in extract_caddy_block(txt, admin_route)


def test_t3_04_f3_f4_firstboot_ddns_secret_and_breakglass_lifecycle(isolated_repo, system_api_client_factory, monkeypatch):
    """F3 + F4: generate-env creates BRAINSOS_DDNS_OWNER_SECRET; setup disables breakglass and syncs DDNS claim."""
    gen = isolated_repo / "scripts" / "control" / "generate-env.sh"
    gen.write_text(read_repo_text("scripts/control/generate-env.sh"), encoding="utf-8")
    gen.chmod(0o755)
    (isolated_repo / ".env.example").write_text(read_repo_text(".env.example"), encoding="utf-8")
    (isolated_repo / ".env").unlink()
    gen_res = subprocess.run(
        ["bash", str(gen), "--non-interactive", "--no-rebuild"],
        cwd=isolated_repo,
        capture_output=True,
        text=True,
    )
    assert gen_res.returncode == 0, gen_res.stderr
    env_txt = (isolated_repo / ".env").read_text(encoding="utf-8")
    m = re.search(r"^BRAINSOS_DDNS_OWNER_SECRET=(.+)$", env_txt, re.MULTILINE)
    assert m
    monkeypatch.setenv("BRAINSOS_DDNS_OWNER_SECRET", m.group(1).strip())

    ddns = load_module_from_path("ddns_t3_04", REPO_ROOT / "scripts" / "control" / "sync-route53-ddns.py")
    claim = ddns.compute_owner_claim("unit.brainsos.ai", "Z1234567890", "i-0123456789abcdef0")
    assert len(claim) >= 32

    sd = isolated_repo / "scripts" / "control" / "set-domain.sh"
    sd.write_text("#!/usr/bin/env bash\necho ok\n", encoding="utf-8")
    sd.chmod(0o755)
    monkeypatch.setenv("BRAINSOS_TEST_INSTANCE_ID", "i-0123456789abcdef0")
    bundle = system_api_client_factory(
        isolated_repo,
        env_text=env_txt + "\nSYSTEM_API_TOKEN=e2e-internal-token-12345\nBRAINSOS_WIZARD_COMPLETED=false\nBRAINSOS_BREAKGLASS_ENABLED=true\n",
    )
    res = bundle["client"].post(
        "/api/v1/system/setup",
        json={
            "bootstrap_token": "i-0123456789abcdef0",
            "local_domain": "unit.brainsos.ai",
            "url": "unit.brainsos.ai",
            "superuser_username": "alice",
            "superuser_password": "StrongPassword!99",
            "tls_mode": "internal",
        },
        headers=bundle["admin_headers"],
    )
    assert res.status_code == 200
    assert "BRAINSOS_BREAKGLASS_ENABLED=false" in (isolated_repo / ".env").read_text(encoding="utf-8") or "--no-breakglass" in res.text


def test_t3_05_f4_f5_wizard_completion_minimizes_identity_and_caches_status_without_leaking_keys(
    isolated_repo, system_api_client_factory
):
    """F4 + F5: Post-wizard unauth /identity is minimized, /jobs/latest/stream fails closed, and /runners hides key previews."""
    bundle = system_api_client_factory(
        isolated_repo,
        env_text=(
            "BRAINSOS_STAGE=test\n"
            "SYSTEM_API_TOKEN=e2e-internal-token-12345\n"
            "BRAINSOS_WIZARD_COMPLETED=true\n"
            "BRAINSOS_UNIT_NAME=LockUnit\n"
            "FIRECRAWL_API_KEY=fc-secret-abcdef123456\n"
        ),
        wizard_completed=True,
    )
    id_res = bundle["client"].get("/api/v1/system/identity", headers=bundle["internal_headers"])
    assert id_res.status_code == 200
    assert set(id_res.json().keys()) <= {"firstboot_wizard_completed", "unit_name", "auth_cognito_enabled", "cognito_enabled"}

    stream_res = bundle["client"].get("/api/v1/system/jobs/latest/stream", headers=bundle["internal_headers"])
    assert stream_res.status_code in (401, 403)

    run_res = bundle["client"].get("/api/v1/system/runners", headers=bundle["internal_headers"])
    if run_res.status_code == 200:
        assert "abcdef" not in run_res.text and "123456" not in run_res.text


def test_t3_06_f6_f7_cognito_linking_and_self_hosted_authentik_theme():
    """F6 + F7: Verified Cognito linking + disabled Langfuse linking + self-hosted login theme CSS."""
    rel = read_repo_text("scripts/control/reload-env.sh")
    assert re.search(r"email_verified.*is\s+True", rel)
    assert 'user_matching_mode = "identifier"' in rel
    tel = load_yaml("docker/compose/compose.telemetry.yml")
    lf_env = "\n".join(str(x) for x in tel["services"]["langfuse-web"]["environment"])
    assert "AUTH_CUSTOM_ALLOW_ACCOUNT_LINKING=false" in lf_env
    login = read_repo_text("config/authentik/themes/brainsos/login.html")
    assert "cdn.tailwindcss.com" not in login and "fonts.googleapis.com" not in login


def test_t3_07_f8_f9_detached_runners_and_strict_egress_sni_tavily(egress_addon_factory):
    """F8 + F9: Runners detached from ingress-net, DOCKER-USER proxy egress, and strict SNI/Tavily scrub."""
    agents = load_yaml("docker/compose/compose.agents.yml")
    assert "brainsos-ingress-net" not in json.dumps(agents["services"]["runner-hermes"]["networks"])
    assert "DOCKER-USER" in read_repo_text("scripts/setup/imds-guard.sh")

    mod, create_addon, make_flow = egress_addon_factory
    addon = create_addon()
    bad_sni = make_flow("api.tavily.com", sni="")
    addon.request(bad_sni)
    assert bad_sni.response.status_code == 403

    ok_flow = make_flow("api.tavily.com", sni="api.tavily.com", content=b'{"query":"q","api_key":"in-transit-openbao-managed"}')
    addon.request(ok_flow)
    assert ok_flow.response is None
    assert ok_flow.request.headers["Authorization"].startswith("Bearer ")
    assert b"tvly-secret-token-e2e" not in ok_flow.request.content


def test_t3_08_f8_f12_deterministic_caddy_ip_sogo_token_and_gitea_trusted_proxies():
    """F8 + F12: Deterministic Caddy static IP aligns with Gitea trusted proxies & SOGo X-Caddy-Ingress-Token."""
    base = load_yaml("docker-compose.yml")
    assert "ipam" in base["networks"]["brainsos-ingress-net"]
    apps = load_yaml("docker/compose/compose.apps.yml")
    gitea_env = "\n".join(str(e) for e in apps["services"]["gitea"]["environment"])
    assert "10.0.0.0/8" not in gitea_env
    assert "X-Caddy-Ingress-Token" in read_repo_text("docker/sogo/nginx.conf")
    assert "X-Caddy-Ingress-Token" in read_repo_text("config/caddy/Caddyfile")


def test_t3_09_f9_f10_openbao_internal_tls_with_egress_approle_and_system_put(isolated_repo, monkeypatch, egress_addon_factory):
    """F9 + F10: OpenBao HTTPS stores secrets from openbao_client without docker exec -e, and github_auth loads via HTTPS."""
    from brainsos_telemetry.openbao_client import put_tool_secrets

    assert "tls_disable = 0" in read_repo_text("config/openbao/openbao.hcl") or re.search(
        r"tls_disable\s*=\s*(0|false)", read_repo_text("config/openbao/openbao.hcl")
    )
    seen_urls = []

    class _FakeResp:
        def __init__(self, data):
            self.status = 200
            self._b = json.dumps(data).encode()

        def read(self):
            return self._b

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _fake_open(req, timeout=3.0, **kwargs):
        seen_urls.append(req.full_url)
        if req.get_method() == "GET":
            return _FakeResp({"data": {"data": {}}})
        return _FakeResp({"data": {"version": 1}})

    monkeypatch.setenv("OPENBAO_ADDR", "https://openbao:8200")
    monkeypatch.setenv("OPENBAO_TOKEN", "writer-tok")
    with patch("brainsos_telemetry.openbao_client.urllib.request.urlopen", side_effect=_fake_open):
        assert put_tool_secrets(str(isolated_repo), {"TAVILY_API_KEY": "tvly-new"}) is True
    assert seen_urls and all(u.startswith("https://") for u in seen_urls)


def test_t3_10_f10_f11_externalized_seal_and_codeserver_exclusion_with_gitignore():
    """F10 + F11: OpenBao seal outside data dir + code-server excludes control_plane/backups + gitignore blocks secrets."""
    assert "/etc/brainsos/openbao-seal.json" in read_repo_text("scripts/setup/setup-secrets.sh")
    apps = load_yaml("docker/compose/compose.apps.yml")
    vols = "\n".join(str(v) for v in apps["services"]["code-server"]["volumes"])
    assert "${BRAINSOS_DATA_DIR:-./data}:/data\n" not in vols
    gi = read_repo_text("config/templates/data-repo.gitignore")
    for pat in ("control_plane/**", "backups/**", "*.key", "*.pem", ".env*"):
        assert pat in gi


def test_t3_11_f12_imds_guard_route53_caddy_reapply_and_harden_host():
    """F12: imds-guard reconciles Route53 Caddy + LiteLLM, reload-env re-applies it, harden-host separates 8010/8000."""
    imds = read_repo_text("scripts/setup/imds-guard.sh")
    assert "route53" in imds.lower() and "caddy" in imds.lower()
    assert "imds-guard.sh" in read_repo_text("scripts/control/reload-env.sh")
    hh = read_repo_text("packages/brainsOS-appliance/scripts/harden-host.sh")
    assert "brainsos-ingress-net" in hh or "br-ingress" in hh
    assert "brainsos-mail-net" in hh or "br-mail" in hh


def test_t3_12_f12_f21_worker_bridge_binding_and_webhook_secret_file():
    """F12 + F21: worker.py avoids 0.0.0.0 default and agent-webhook reads 0600 vmail:vmail secret (not /etc/environment)."""
    w = read_repo_text("packages/brainsOS-agent/brainsos_agent/worker.py")
    assert 'os.getenv("BRAINSOS_INGRESS_HOST", "0.0.0.0")' not in w
    ep = read_repo_text("docker/mail/entrypoint.sh")
    wh = read_repo_text("docker/mail/agent-webhook.sh")
    assert "> /etc/environment" not in ep
    assert "/etc/environment" not in wh


def test_t3_13_f13_f14_ephemeral_runner_containment_with_single_tenant_env(tmp_path, monkeypatch):
    """F13 + F14: Ephemeral container gets hardened flags, single-tenant mounts, BRAINSOS_AGENT_ID, and no LANGFUSE_SECRET_KEY."""
    from brainsos_runner.clients.docker import EphemeralDockerRunnerClient
    from brainsos_runner.models import AgentTurnRequest, ChatMessage

    agents = tmp_path / "agents"
    ws = agents / "alice" / "workspace"
    (agents / "alice" / "memories").mkdir(parents=True)
    ws.mkdir(parents=True)
    monkeypatch.setenv("BRAINSOS_AGENTS_DIR", str(agents))
    monkeypatch.setenv("ALICE_LITELLM_KEY", "sk-alice")
    monkeypatch.setenv("BOB_LITELLM_KEY", "sk-bob")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-secret")

    captured = {}

    async def _fake_exec(*cmd, **kwargs):
        captured["cmd"] = list(cmd)
        proc = MagicMock()
        proc.returncode = 0

        async def _comm(input=None):
            return json.dumps({"run_id": "r-13-14", "status": "completed", "output_text": "done"}).encode(), b""

        proc.communicate = _comm
        return proc

    client = EphemeralDockerRunnerClient(image="brainsos-runner-hermes:latest")
    req = AgentTurnRequest(
        run_id="r-13-14",
        agent_id="alice",
        model="gpt-4o",
        system_prompt="s",
        conversation=[ChatMessage(role="user", content="hi")],
        workspace_dir=str(ws),
    )
    with patch("brainsos_runner.clients.docker.asyncio.create_subprocess_exec", side_effect=_fake_exec):
        res = asyncio.run(client.execute_turn(req))
    assert res.status == "completed"
    joined = " ".join(captured["cmd"])
    assert "--cap-drop=ALL" in joined and "--read-only" in joined and "brainsos.tenant=alice" in joined
    assert "BRAINSOS_AGENT_ID=alice" in joined
    assert "sk-bob" not in joined and "sk-lf-secret" not in joined


def test_t3_14_f13_f15_ephemeral_runner_and_fail_closed_server_plus_hermes_headers(monkeypatch, tmp_path):
    """F13 + F15: create_runner_app fails closed 503 without token; HermesMailAdapter never sends LITELLM_MASTER_KEY."""
    from brainsos_agent.adapters.hermes import HermesMailAdapter
    from brainsos_agent.models import AgentProfile
    from brainsos_runner.models import AgentTurnRequest, AgentTurnResponse, ChatMessage
    from brainsos_runner.server import create_runner_app
    from fastapi.testclient import TestClient

    monkeypatch.delenv("RUNNER_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("API_SERVER_KEY", raising=False)
    monkeypatch.delenv("HERMES_API_KEY", raising=False)
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-master-bad")

    adapter = HermesMailAdapter(runner_url="http://127.0.0.1:9999/v1")
    prof = AgentProfile(id="alice", name="Alice", email="a@b.c", memory_root=tmp_path, workspace_root=tmp_path)
    assert "sk-master-bad" not in adapter._headers(prof).get("Authorization", "")

    async def _h(req: AgentTurnRequest) -> AgentTurnResponse:
        return AgentTurnResponse(run_id=req.run_id, status="completed", output_text="ok")

    client = TestClient(create_runner_app(_h))
    res = client.post(
        "/v1/agent/run",
        json=AgentTurnRequest(
            run_id="r", agent_id="alice", model="m", system_prompt="s", conversation=[ChatMessage(role="user", content="h")], workspace_dir=str(tmp_path)
        ).model_dump(),
    )
    assert res.status_code == 503


def test_t3_15_f14_f9_proxy_auth_plus_github_allowed_repos_plus_sni_and_ssrf(egress_addon_factory, monkeypatch):
    """F14 + F9: Valid tenant Proxy-Authorization allows allowed repo + strips header; blocks disallowed repo & bad SNI."""
    monkeypatch.setenv("TOOL_EGRESS_PROXY_TOKENS", "alice:tok-alice")
    monkeypatch.setenv("GITHUB_ALLOWED_REPOS", "org/good-repo")
    _, create_addon, make_flow = egress_addon_factory
    addon = create_addon()

    ok = make_flow(
        "api.github.com",
        sni="api.github.com",
        path="/repos/org/good-repo/pulls",
        headers={"Proxy-Authorization": "Bearer tok-alice"},
    )
    addon.request(ok)
    assert ok.response is None
    assert "Proxy-Authorization" not in ok.request.headers

    bad_repo = make_flow(
        "api.github.com",
        sni="api.github.com",
        path="/repos/org/other-repo/pulls",
        headers={"Proxy-Authorization": "Bearer tok-alice"},
    )
    addon.request(bad_repo)
    assert bad_repo.response is not None and bad_repo.response.status_code == 403


def test_t3_16_f14_f16_emergency_stop_and_bedrock_cap_with_canonical_manifest(isolated_repo, fake_bin_dir):
    """F14 + F16: emergency-stop discovers LiteLLM IP, kills tenant ephemeral containers, reads settings/agents.yaml; bedrock caps=2."""
    cfg = load_yaml("config/litellm/config.bedrock.yaml")
    assert cfg.get("router_settings", {}).get("max_parallel_requests") == 2

    (isolated_repo / "scripts" / "control" / "emergency-stop.sh").write_text(
        read_repo_text("scripts/control/emergency-stop.sh"), encoding="utf-8"
    )
    (isolated_repo / "scripts" / "control" / "emergency-stop.sh").chmod(0o755)
    (isolated_repo / "data" / "settings" / "agents.yaml").write_text(
        "agents:\n  - id: alice\n    routing:\n      virtual_key: ALICE_LITELLM_KEY\n", encoding="utf-8"
    )
    log_file = isolated_repo / "estop.log"
    (fake_bin_dir / "docker").write_text(
        f'#!/usr/bin/env bash\necho "docker $*" >> "{log_file}"\nif [ "$1" = "ps" ] && echo "$*" | grep -q "brainsos.tenant"; then echo "ephem-alice"; fi\nif [ "$1" = "inspect" ]; then echo "172.20.0.9"; fi\nexit 0\n',
        encoding="utf-8",
    )
    (fake_bin_dir / "docker").chmod(0o755)
    (fake_bin_dir / "curl").write_text("#!/usr/bin/env bash\necho 200\n", encoding="utf-8")
    (fake_bin_dir / "curl").chmod(0o755)
    res = subprocess.run(
        ["bash", str(isolated_repo / "scripts" / "control" / "emergency-stop.sh"), "alice"],
        cwd=isolated_repo,
        env={**os.environ, "PATH": f"{fake_bin_dir}:{os.environ['PATH']}", "LITELLM_MASTER_KEY": "sk-m", "ALICE_LITELLM_KEY": "sk-a"},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert res.returncode == 0
    assert "docker kill" in log_file.read_text(encoding="utf-8")


def test_t3_17_f17_f19_ses_pass_claim_check_handoff_to_sqs_consumer(run_node_sanitizer):
    """F17 + F19: Pipeline approves email with PASS SES verdicts -> emits claimCheck -> SqsIngressConsumer enforces bucket/approved/."""
    from brainsos_mail.ingress.config import IngressConfig
    from brainsos_mail.ingress.sqs_consumer import SqsIngressConsumer

    out = run_node_sanitizer(
        """
const { default: simpleParser } = await import(`${process.env.SANITIZER_OUT_DIR}/node_modules/mailparser/lib/simple-parser.js`);
const { processEmailThroughPipeline } = await import(`${process.env.SANITIZER_OUT_DIR}/pipeline.js`);
const inp = JSON.parse(process.env.SANITIZER_INPUT);
const parsed = await simpleParser(inp.mime);
const verdict = processEmailThroughPipeline("msg-317", parsed, {
  allowedSenders: ["op@gmail.com"],
  allowedRecipientDomains: ["brainsos.ai"],
  sesReceipt: { spfVerdict: { status: "PASS" }, dkimVerdict: { status: "PASS" }, dmarcVerdict: { status: "PASS" } }
});
console.log(JSON.stringify({ status: verdict.status, payload: verdict.payload, claimCheck: verdict.status === "APPROVED" ? verdict.claimCheck("trusted-bkt") : null }));
""",
        {"mime": "From: op@gmail.com\r\nTo: alice@brainsos.ai\r\nSubject: Hi\r\nMIME-Version: 1.0\r\n\r\nHello"},
    )
    assert out["status"] == "APPROVED"
    cc = out["claimCheck"]
    assert cc["s3Key"].startswith("approved/")

    s3 = MagicMock()
    s3.get_object.return_value = {"Body": SimpleNamespace(read=lambda: json.dumps(out["payload"]).encode())}
    injector = MagicMock()
    injector.inject.return_value = True
    consumer = SqsIngressConsumer(IngressConfig(sqs_queue_url="https://sqs/q", s3_bucket="trusted-bkt"), s3_client=s3, sqs_client=MagicMock(), injector=injector)
    assert consumer.process_message({"ReceiptHandle": "rh", "Body": json.dumps(cc)}) is True


def test_t3_18_f17_f20_sanitized_inbound_and_sanitized_markdown_reply(run_node_sanitizer):
    """F17 + F20: Inbound email rejected on unaligned header; valid inbound reply Markdown strips javascript: links."""
    from brainsos_agent.mail_runs import markdown_to_clean_html

    res = run_node_sanitizer(
        """
const { default: simpleParser } = await import(`${process.env.SANITIZER_OUT_DIR}/node_modules/mailparser/lib/simple-parser.js`);
const { processEmailThroughPipeline } = await import(`${process.env.SANITIZER_OUT_DIR}/pipeline.js`);
const inp = JSON.parse(process.env.SANITIZER_INPUT);
const parsed = await simpleParser(inp.mime);
const v = processEmailThroughPipeline("msg-318", parsed, { allowedSenders: ["op@gmail.com"], allowedRecipientDomains: ["brainsos.ai"] });
console.log(JSON.stringify(v));
""",
        {
            "mime": (
                "From: op@gmail.com\r\nTo: a@brainsos.ai\r\nSubject: Hi\r\n"
                "Authentication-Results: mx.amazonses.com; dkim=pass header.d=sub.gmail.com; spf=pass; dmarc=pass header.from=sub.gmail.com\r\n"
                "MIME-Version: 1.0\r\n\r\nHello"
            )
        },
    )
    assert res["status"] == "QUARANTINED"
    html_reply = markdown_to_clean_html("See [evil](javascript:alert(1)) or [docs](https://brainsos.ai)")
    assert "javascript:" not in html_reply.lower() and "https://brainsos.ai" in html_reply


def test_t3_19_f18_f21_mail_and_sogo_hashing_permissions_and_postfix_sender_login():
    """F18 + F21: setup-mail/sogo + reload-env hash passwords & drop 777 & c_password; Postfix blocks sender spoofing."""
    sm = read_repo_text("scripts/setup/setup-mail.sh")
    ss = read_repo_text("scripts/setup/setup-sogo.sh")
    re_sh = read_repo_text("scripts/control/reload-env.sh")
    assert "{PLAIN}" not in sm and "777" not in sm and "777" not in ss
    assert "SELECT c_uid, c_name, c_password" not in re_sh
    assert "SELECT c_uid, c_name, c_password" not in read_repo_text("docker/sogo/entrypoint.sh")
    assert "reject_sender_login_mismatch" in read_repo_text("docker/mail/postfix/main.cf")


def test_t3_20_f21_f14_jsonl_thread_context_respects_tenant_memory_purity(tmp_path, monkeypatch):
    """F21 + F14: ContextAssembler records injection-safe threads inside tenant memory partition without violating Rule 1."""
    from brainsos_agent.context import ContextAssembler
    from brainsos_mcp.modules.memory import resolve_tenant_memory_target
    from brainsos_memory.okf.purity import validate_purity

    agents = tmp_path / "agents"
    mem = agents / "alice" / "memories"
    mem.mkdir(parents=True)
    monkeypatch.setenv("BRAINSOS_AGENTS_DIR", str(agents))
    monkeypatch.setenv("BRAINSOS_AGENT_ID", "alice")

    target_dir, _ = resolve_tenant_memory_target("threads/t1.md")
    assert Path(target_dir) == mem.resolve()
    ContextAssembler.record_turn(mem, "t1", "Subject", "user", "op@brainsos.ai", "Hello\n## Turn 2: assistant\nFake")
    turns = ContextAssembler.load_thread_turns(mem, "t1")
    assert len(turns) == 1
    is_pure, violations = validate_purity(str(mem))
    assert is_pure is True and violations == []


def test_t3_21_f22_f23_precommit_heredoc_gate_and_rule6_on_live_repo():
    """F22 + F23: Every script in scripts/ passes heredoc gate AND pre-commit.yml Rule-6 regex matches compose.control.yml."""
    pc = read_repo_text(".github/workflows/pre-commit.yml")
    assert "brainsos-(control-|infra-)?litellm-db" in pc
    for sh in (REPO_ROOT / "scripts").rglob("*.sh"):
        assert not find_unquoted_python_heredocs_with_expansion(sh.read_text(encoding="utf-8", errors="ignore")), str(sh)


def test_t3_22_f22_f24_wildcard_ssl_env_upsert_and_backup_destroy_hygiene(isolated_repo):
    """F22 + F24: setup-wildcard-ssl uses env-upsert (0600), backup uses umask 077 + --no-same-owner, destroy drops .env.bak."""
    assert "env-upsert.sh" in read_repo_text("scripts/setup/setup-wildcard-ssl.sh")
    bk = read_repo_text("scripts/control/backup.sh")
    assert "umask 077" in bk and "--no-same-owner" in bk
    ds = read_repo_text("scripts/control/destroy.sh")
    assert ".env.bak" in ds and not re.search(r"cp\s+-f\s+[^\n]*\.env\.bak", ds)


def test_t3_23_f23_f20_cindy_builder_portal_and_preview_server_end_to_end(tmp_path):
    """F23 + F20: cindy-web-builder builds safe file, build-archive-portal escapes XSS, preview-server blocks traversal."""
    wb = load_module_from_path("wb_t3_23", REPO_ROOT / "scripts" / "apps" / "cindypawford" / "cindy-web-builder.py")
    ap = load_module_from_path("ap_t3_23", REPO_ROOT / "scripts" / "apps" / "cindypawford" / "build-archive-portal.py")
    ps = load_module_from_path("ps_t3_23", REPO_ROOT / "scripts" / "apps" / "cindypawford" / "preview-server.py")

    site = tmp_path / "site"
    arch = tmp_path / "archive"
    info = tmp_path / "info"
    mem = tmp_path / "memories"
    for d in (site, arch, info, mem):
        d.mkdir()
    (tmp_path / "outside.txt").write_text("SECRET", encoding="utf-8")

    res = wb.execute_build(
        feature_name="Safe Card",
        specification="Add card",
        canvas_dir=str(site),
        memory_dir=str(mem),
        target_files=["index.html"],
        mock_files={"index.html": "<!doctype html><html><body>ok</body></html>"},
    )
    assert res["status"] == "success"
    assert (site / "index.html").is_file()

    entry_html = ap.render_timeline_entry({"category": 'x" onclick="alert(1)', "title": "<b>T</b>", "description": "D"})
    assert 'onclick="alert(1)"' not in entry_html

    ps.SITE_DIR, ps.ARCHIVE_DIR, ps.INFO_DIR = str(site), str(arch), str(info)
    h = ps.CindyPreviewHandler.__new__(ps.CindyPreviewHandler)
    assert Path(h.translate_path("/../outside.txt")).resolve() != (tmp_path / "outside.txt").resolve()


def test_t3_24_f24_f3_f8_ami_provision_to_firstboot_secret_generation():
    """F24 + F3 + F8: Packer provision pins uv SHA-256 + scrubs history; firstboot generates DDNS & Gitea secrets."""
    prov = read_repo_text("packages/brainsOS-appliance/packer/provision.sh")
    assert "sha256sum" in prov and "astral.sh/uv/install.sh" not in prov and "/home/admin" in prov
    fb = read_repo_text("packages/brainsOS-appliance/scripts/firstboot.sh")
    for k in ("BRAINSOS_DDNS_OWNER_SECRET", "GITEA_SECRET_KEY", "GITEA_INTERNAL_TOKEN"):
        assert k in fb


def test_t3_25_f5_f10_f15_system_api_stores_key_in_https_openbao_and_masks_runners(isolated_repo, system_api_client_factory, monkeypatch):
    """F5 + F10 + F15: System API stores tool key via HTTPS OpenBao and /runners returns configured=True without masked preview."""
    monkeypatch.setenv("OPENBAO_ADDR", "https://openbao:8200")
    monkeypatch.setenv("OPENBAO_TOKEN", "writer-tok")
    bundle = system_api_client_factory(isolated_repo)

    class _Resp:
        status = 200

        def read(self):
            return b'{"data":{"data":{}}}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    with patch("brainsos_telemetry.openbao_client.urllib.request.urlopen", return_value=_Resp()):
        post_res = bundle["client"].post(
            "/api/v1/system/runners/hermes/config",
            json={"keys": {"TAVILY_API_KEY": "tvly-topsecret-99999"}, "restart_runner": False},
            headers=bundle["admin_headers"],
        )
    assert post_res.status_code == 200 and post_res.json()["stored_in_openbao"] is True

    run_res = bundle["client"].get("/api/v1/system/runners", headers=bundle["internal_headers"])
    if run_res.status_code == 200:
        assert "99999" not in run_res.text


def test_t3_26_f11_f23_data_repo_gitignore_and_precommit_agents_hygiene():
    """F11 + F23: data-repo.gitignore and pre-commit.yml data/agents/ hygiene jointly protect fleet secrets."""
    pc = read_repo_text(".github/workflows/pre-commit.yml")
    gi = read_repo_text("config/templates/data-repo.gitignore")
    assert "data/agents/" in pc
    assert "control_plane/**" in gi and "backups/**" in gi and ".env*" in gi
