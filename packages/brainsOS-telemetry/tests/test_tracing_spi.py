"""Unit tests for the Vendor-Neutral OpenTelemetry GenAI Telemetry SPI (Ticket #382)."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from brainsos_telemetry import (
    LangfuseOTLPSink,
    LensOTLPSink,
    OTelTraceDispatcher,
    TraceSink,
    create_system_api_app,
    deterministic_trace_id,
    mint_span_id,
    mint_traceparent,
    parse_traceparent,
    resolve_active_backends,
)
from brainsos_telemetry.system import ALLOWED_SERVICES
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[3]


def _span_attrs(span: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for kv in span.get("attributes", []):
        val = kv["value"]
        if "arrayValue" in val:
            out[kv["key"]] = [v["stringValue"] for v in val["arrayValue"]["values"]]
        else:
            out[kv["key"]] = next(iter(val.values()))
    return out


def _workflow_kwargs(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "session_id": "mail-bawtford-thread_382",
        "agent_id": "bawtford",
        "agent_name": "Bawtford",
        "sender": "operator@brainsos.local",
        "subject": "Verify OTel SPI",
        "run_id": "run_382",
        "status": "completed",
        "input_text": "Check GenAI telemetry.",
        "output_text": "Telemetry SPI verified.",
        "error": None,
        "usage": {"input_tokens": 32, "output_tokens": 16},
        "started_at": 1_700_000_100.0,
        "ended_at": 1_700_000_105.0,
    }
    base.update(overrides)
    return base


# ------------------------------------------------------------------ Backend Routing


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({}, (True, True)),
        ({"BRAINSOS_TELEMETRY_BACKEND": ""}, (True, True)),
        ({"BRAINSOS_TELEMETRY_BACKEND": "dual"}, (True, True)),
        ({"BRAINSOS_TELEMETRY_BACKEND": "DUAL"}, (True, True)),
        ({"BRAINSOS_TELEMETRY_BACKEND": "lens,langfuse"}, (True, True)),
        ({"BRAINSOS_TELEMETRY_BACKEND": "lens"}, (True, False)),
        ({"BRAINSOS_TELEMETRY_BACKEND": "LENS"}, (True, False)),
        ({"BRAINSOS_TELEMETRY_BACKEND": "langfuse"}, (False, True)),
        ({"BRAINSOS_TELEMETRY_BACKEND": "none"}, (False, False)),
        ({"BRAINSOS_TELEMETRY_BACKEND": "off"}, (False, False)),
        ({"BRAINSOS_TELEMETRY_BACKEND": "disabled"}, (False, False)),
        ({"BRAINSOS_TELEMETRY_BACKEND": "dual", "LANGFUSE_ENABLED": "false"}, (True, False)),
        ({"BRAINSOS_TELEMETRY_BACKEND": "dual", "LENS_ENABLED": "0"}, (False, True)),
        ({"BRAINSOS_TELEMETRY_BACKEND": "lens", "LENS_ENABLED": "false"}, (False, False)),
        ({"BRAINSOS_TELEMETRY_BACKEND": "langfuse", "LANGFUSE_ENABLED": "off"}, (False, False)),
    ],
)
def test_resolve_active_backends_matrix(env: dict[str, str], expected: tuple[bool, bool]) -> None:
    assert resolve_active_backends(env) == expected


# ------------------------------------------------------------------ Deterministic Trace & W3C Traceparent


def test_deterministic_trace_id_and_w3c_traceparent_roundtrip() -> None:
    sid = "mail-terrastella-alpha"
    expected_default = hashlib.sha256(f"{sid}::{sid}".encode("utf-8")).digest()[:16].hex()
    assert deterministic_trace_id(sid) == expected_default
    assert len(expected_default) == 32

    expected_task = hashlib.sha256(f"{sid}::run-99".encode("utf-8")).digest()[:16].hex()
    assert deterministic_trace_id(sid, "run-99") == expected_task
    assert expected_task != expected_default

    assert deterministic_trace_id("") == hashlib.sha256(b"sessionless::sessionless").digest()[:16].hex()

    sp = mint_span_id()
    assert len(sp) == 16

    tp, trace_id, span_id = mint_traceparent(sid, "run-99")
    assert trace_id == expected_task
    assert len(span_id) == 16
    assert tp == f"00-{trace_id}-{span_id}-01"
    assert parse_traceparent(tp) == (trace_id, span_id)

    fixed_span = "abcdef0123456789"
    tp_fixed, _, sp_fixed = mint_traceparent(sid, "run-99", span_id=fixed_span)
    assert sp_fixed == fixed_span
    assert parse_traceparent(tp_fixed) == (expected_task, fixed_span)

    # Reject invalid / all-zero headers
    assert parse_traceparent(None) == ("", "")
    assert parse_traceparent("invalid") == ("", "")
    assert parse_traceparent(f"ff-{trace_id}-{fixed_span}-01") == ("", "")
    assert parse_traceparent(f"00-{'0' * 32}-{fixed_span}-01") == ("", "")
    assert parse_traceparent(f"00-{trace_id}-{'0' * 16}-01") == ("", "")


# ------------------------------------------------------------------ TraceSink Protocol & Workflow Dispatch


def test_sink_protocol_and_workflow_dispatch_modes() -> None:
    assert isinstance(LensOTLPSink(), TraceSink)
    assert isinstance(LangfuseOTLPSink(), TraceSink)

    base_env = {
        "LENS_OTLP_ENDPOINT": "http://lens.unit:4318",
        "LITELLM_TRACING_KEY": "lens-secret-382",
        "BRAINSOS_LANGFUSE_URL": "http://langfuse.unit:3000",
        "LANGFUSE_PUBLIC_KEY": "pk-lf-382",
        "LANGFUSE_SECRET_KEY": "sk-lf-382",
        "BRAINSOS_LOCAL_DOMAIN": "box.brainsos.local",
    }

    captured: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(
            {
                "url": str(req.url),
                "headers": dict(req.headers),
                "payload": json.loads(req.content),
            }
        )
        return httpx.Response(200, json={"ok": True})

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            # 1. Dual mode exports to both Lens and Langfuse
            disp_dual = OTelTraceDispatcher.from_env({**base_env, "BRAINSOS_TELEMETRY_BACKEND": "dual"})
            res_dual = await disp_dual.record_workflow_run(http_client=client, **_workflow_kwargs())
            assert res_dual == {"lens": True, "langfuse": True}
            assert len(captured) == 2

            urls = {c["url"]: c for c in captured}
            assert "http://lens.unit:4318/v1/traces" in urls
            assert "http://langfuse.unit:3000/api/public/otel/v1/traces" in urls

            lens_call = urls["http://lens.unit:4318/v1/traces"]
            assert lens_call["headers"]["authorization"] == "Bearer lens-secret-382"
            lens_span = lens_call["payload"]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
            assert _span_attrs(lens_span)["gen_ai.operation.name"] == "invoke_workflow"

            lf_call = urls["http://langfuse.unit:3000/api/public/otel/v1/traces"]
            expected_basic = base64.b64encode(b"pk-lf-382:sk-lf-382").decode("ascii")
            assert lf_call["headers"]["authorization"] == f"Basic {expected_basic}"
            assert lf_call["headers"]["x-langfuse-ingestion-version"] == "4"

            # 2. Lens-only mode skips Langfuse completely
            captured.clear()
            disp_lens = OTelTraceDispatcher.from_env({**base_env, "BRAINSOS_TELEMETRY_BACKEND": "lens"})
            res_lens = await disp_lens.record_workflow_run(http_client=client, **_workflow_kwargs())
            assert res_lens == {"lens": True, "langfuse": False}
            assert [c["url"] for c in captured] == ["http://lens.unit:4318/v1/traces"]

            # 3. Langfuse-only mode skips Lens completely
            captured.clear()
            disp_lf = OTelTraceDispatcher.from_env({**base_env, "BRAINSOS_TELEMETRY_BACKEND": "langfuse"})
            res_lf = await disp_lf.record_workflow_run(http_client=client, **_workflow_kwargs())
            assert res_lf == {"lens": False, "langfuse": True}
            assert [c["url"] for c in captured] == ["http://langfuse.unit:3000/api/public/otel/v1/traces"]

            # 4. None mode emits zero requests
            captured.clear()
            disp_none = OTelTraceDispatcher.from_env({**base_env, "BRAINSOS_TELEMETRY_BACKEND": "none"})
            res_none = await disp_none.record_workflow_run(http_client=client, **_workflow_kwargs())
            assert res_none == {"lens": False, "langfuse": False}
            assert captured == []

    import asyncio

    asyncio.run(exercise())


# ------------------------------------------------------------------ Runner Turn Span Hierarchy


@pytest.mark.asyncio
async def test_record_runner_turn_emits_genai_and_gateway_transport_spans() -> None:
    env = {
        "BRAINSOS_TELEMETRY_BACKEND": "lens",
        "LENS_OTLP_ENDPOINT": "http://lens.unit:4318",
        "LITELLM_TRACING_KEY": "lens-runner-382",
        "BRAINSOS_LOCAL_DOMAIN": "appliance.brainsos.local",
    }
    captured: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(json.loads(req.content))
        return httpx.Response(200, json={})

    session_id = "runner-session-382"
    run_id = "turn-001"
    tp, trace_id, tp_span_id = mint_traceparent(session_id, run_id)
    assert tp.startswith(f"00-{trace_id}-{tp_span_id}-01")

    dispatcher = OTelTraceDispatcher.from_env(env)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        outcomes = await dispatcher.record_runner_turn(
            agent_id="gpt",
            session_id=session_id,
            run_id=run_id,
            model="brainsos-core-reasoner",
            input_text="Summarize memory files.",
            output_text="Summary complete.",
            started_at=1_700_000_200.0,
            ended_at=1_700_000_203.5,
            prompt_tokens=140,
            completion_tokens=45,
            trace_id=trace_id,
            transport_span_id=tp_span_id,
            tool_calls=[
                {
                    "id": "call_1",
                    "tool_name": "read_memory",
                    "arguments": {"path": "notes.md"},
                    "output": "contents",
                    "exit_code": 0,
                }
            ],
            http_client=client,
        )

    assert outcomes == {"lens": True, "langfuse": False}
    assert len(captured) == 1
    scope_blocks = {
        b["scope"]["name"]: b["spans"]
        for b in captured[0]["resourceSpans"][0]["scopeSpans"]
    }
    assert "brainsos.telemetry.genai" in scope_blocks
    assert "litellm.gateway.client" in scope_blocks

    genai_spans = scope_blocks["brainsos.telemetry.genai"]
    gw_spans = scope_blocks["litellm.gateway.client"]
    assert len(genai_spans) == 3
    assert len(gw_spans) == 1

    by_op = {_span_attrs(s)["gen_ai.operation.name"]: s for s in genai_spans}
    root_span = by_op["invoke_agent"]
    chat_span = by_op["chat"]
    tool_span = by_op["execute_tool"]
    gw_span = gw_spans[0]

    for s in (*genai_spans, gw_span):
        assert s["traceId"] == trace_id

    assert chat_span["parentSpanId"] == root_span["spanId"]
    assert tool_span["parentSpanId"] == root_span["spanId"]
    assert gw_span["parentSpanId"] == chat_span["spanId"]
    assert gw_span["spanId"] == tp_span_id
    assert _span_attrs(gw_span)["litellm.gateway.attempt"] == "true"

    chat_attrs = _span_attrs(chat_span)
    assert chat_attrs["gen_ai.request.model"] == "brainsos-core-reasoner"
    assert chat_attrs["gen_ai.usage.input_tokens"] == "140"
    assert chat_attrs["gen_ai.usage.output_tokens"] == "45"
    assert _span_attrs(tool_span)["gen_ai.tool.name"] == "read_memory"


# ------------------------------------------------------------------ System Status, Plugin & Terminal URLs


def test_system_status_exposes_telemetry_backend_and_allowed_services(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert {"lens", "telemetry-lens", "clickhouse"} <= ALLOWED_SERVICES

    monkeypatch.setenv("BRAINSOS_STAGE", "test")
    monkeypatch.setenv("SYSTEM_API_TOKEN", "test-secret-token-382")
    monkeypatch.setenv("BRAINSOS_TELEMETRY_BACKEND", "lens")
    monkeypatch.setenv("LENS_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")

    (tmp_path / ".env").write_text("BRAINSOS_DOMAIN=appliance.brainsos.local\n", encoding="utf-8")
    with patch("brainsos_telemetry.system.get_repo_root", return_value=str(tmp_path)):
        client = TestClient(create_system_api_app())
        unauth_res = client.get(
            "/api/v1/system/status",
            headers={"X-BrainsOS-Internal": "test-secret-token-382"},
        )
        assert unauth_res.status_code == 403

        res = client.get(
            "/api/v1/system/status",
            headers={
                "X-BrainsOS-Internal": "test-secret-token-382",
                "X-Authentik-Username": "admin",
                "X-Authentik-Groups": "authentik Admins",
            },
        )
        assert res.status_code == 200
        body = res.json()
        assert body["telemetry_backend"] == "lens"
        assert body["lens_enabled"] is True
        assert body["langfuse_enabled"] is False


def test_hermes_plugin_and_terminal_urls_honor_telemetry_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    from brainsos_agent import langfuse_trace, lens_trace
    from brainsos_terminal.urls import get_service_directory

    plugin_init = REPO_ROOT / "docker/hermes/plugins/observability/langfuse/__init__.py"
    sys.modules.pop("_brainsos_hermes_lens_otel", None)
    spec = importlib.util.spec_from_file_location("hermes_langfuse_plugin_382", plugin_init)
    assert spec and spec.loader
    plugin_mod = importlib.util.module_from_spec(spec)
    sys.modules["hermes_langfuse_plugin_382"] = plugin_mod
    spec.loader.exec_module(plugin_mod)

    monkeypatch.setenv("LITELLM_TRACING_KEY", "lens-key-382")
    monkeypatch.setenv("LENS_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")

    monkeypatch.setenv("BRAINSOS_TELEMETRY_BACKEND", "lens")
    assert lens_trace.is_lens_enabled() is True
    assert langfuse_trace.is_langfuse_enabled() is False
    assert plugin_mod.is_lens_enabled() is True
    assert plugin_mod.is_langfuse_enabled() is False

    monkeypatch.setenv("BRAINSOS_TELEMETRY_BACKEND", "langfuse")
    assert lens_trace.is_lens_enabled() is False
    assert langfuse_trace.is_langfuse_enabled() is True
    assert plugin_mod.is_lens_enabled() is False
    assert plugin_mod.is_langfuse_enabled() is True

    monkeypatch.setenv("BRAINSOS_TELEMETRY_BACKEND", "none")
    assert lens_trace.is_lens_enabled() is False
    assert langfuse_trace.is_langfuse_enabled() is False
    assert plugin_mod.is_lens_enabled() is False
    assert plugin_mod.is_langfuse_enabled() is False

    # Verify terminal URL directory entries across dual / lens / langfuse / none
    names_dual = [s["name"] for s in get_service_directory({"BRAINSOS_DOMAIN": "box.local"})]
    assert "LiteLLM Lens (Telemetry)" in names_dual
    assert "Langfuse Observability" in names_dual

    lens_only = get_service_directory({"BRAINSOS_DOMAIN": "box.local", "BRAINSOS_TELEMETRY_BACKEND": "lens"})
    names_lens = [s["name"] for s in lens_only]
    assert "LiteLLM Lens (Telemetry)" in names_lens
    assert "Langfuse Observability" not in names_lens
    lens_entry = next(s for s in lens_only if s["name"] == "LiteLLM Lens (Telemetry)")
    assert lens_entry["public_url"] == "https://box.local/proxy/ui/?page=lens"
    assert lens_entry["local_url"] == "http://localhost:4000/ui/?page=lens"

    names_lf = [
        s["name"]
        for s in get_service_directory({"BRAINSOS_DOMAIN": "box.local", "BRAINSOS_TELEMETRY_BACKEND": "langfuse"})
    ]
    assert "LiteLLM Lens (Telemetry)" not in names_lf
    assert "Langfuse Observability" in names_lf

    names_none = [
        s["name"]
        for s in get_service_directory({"BRAINSOS_DOMAIN": "box.local", "BRAINSOS_TELEMETRY_BACKEND": "none"})
    ]
    assert "LiteLLM Lens (Telemetry)" not in names_none
    assert "Langfuse Observability" not in names_none


@pytest.mark.asyncio
async def test_stdlib_urllib_transport_and_custom_trace_sink() -> None:
    """Verify zero-dependency stdlib urllib OTLP transport (http_client=None) and custom TraceSink SPI."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    received: list[tuple[str, dict[str, str], dict[str, Any]]] = []

    class _OTLPHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            received.append((self.path, {k.lower(): v for k, v in self.headers.items()}, body))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

    server = HTTPServer(("127.0.0.1", 0), _OTLPHandler)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        sink = LensOTLPSink(endpoint=f"http://127.0.0.1:{port}", tracing_key="stdlib-key-382")

        class _MemorySink:
            name = "memory"

            def __init__(self) -> None:
                self.turns: list[dict[str, Any]] = []

            async def export_workflow_run(self, **kwargs: Any) -> bool:
                return True

            async def export_runner_turn(self, **kwargs: Any) -> bool:
                self.turns.append(kwargs)
                return True

        mem_sink = _MemorySink()
        assert isinstance(mem_sink, TraceSink)
        disp = OTelTraceDispatcher(sinks=[sink, mem_sink])
        res = await disp.record_runner_turn(
            agent_id="claude",
            session_id="sess-stdlib",
            run_id="run-stdlib",
            model="claude-sonnet-4",
            input_text="hi",
            output_text="hello",
            started_at=1_700_000_300.0,
            ended_at=1_700_000_301.0,
        )
        assert res["lens"] is True
        assert res["memory"] is True
        assert len(received) == 1
        assert received[0][0] == "/v1/traces"
        assert received[0][1]["authorization"] == "Bearer stdlib-key-382"
        assert len(mem_sink.turns) == 1
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.asyncio
async def test_openai_and_claude_runners_inject_traceparent_and_record_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify both warm SDK runners attach W3C traceparent headers and dispatch OTel runner turn spans."""
    import types

    from brainsos_runner import AgentTurnRequest, ChatMessage

    recorded_turns: list[dict[str, Any]] = []

    class _FakeDispatcher:
        async def record_runner_turn(self, **kwargs: Any) -> dict[str, bool]:
            recorded_turns.append(kwargs)
            return {"lens": True, "langfuse": False}

    # 1. OpenAI SDK runner
    captured_openai_headers: dict[str, str] = {}

    class _FakeCompletions:
        async def create(self, **kwargs: Any) -> Any:
            msg = types.SimpleNamespace(content="OpenAI reply", tool_calls=None)
            usage = types.SimpleNamespace(prompt_tokens=11, completion_tokens=7)
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)], usage=usage)

    class _FakeAsyncOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            captured_openai_headers.update(kwargs.get("default_headers") or {})
            self.chat = types.SimpleNamespace(completions=_FakeCompletions())

    fake_openai_pkg = types.ModuleType("openai")
    fake_openai_pkg.AsyncOpenAI = _FakeAsyncOpenAI  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", fake_openai_pkg)

    openai_srv_path = REPO_ROOT / "docker/runners/openai-sdk/server.py"
    spec_oa = importlib.util.spec_from_file_location("openai_runner_srv_382", openai_srv_path)
    assert spec_oa and spec_oa.loader
    oa_mod = importlib.util.module_from_spec(spec_oa)
    spec_oa.loader.exec_module(oa_mod)
    monkeypatch.setattr(oa_mod.OTelTraceDispatcher, "from_env", classmethod(lambda cls: _FakeDispatcher()))

    req_oa = AgentTurnRequest(
        run_id="run-oa-1",
        agent_id="gpt",
        model="brainsos-core-reasoner",
        system_prompt="You are helpful.",
        conversation=[ChatMessage(role="user", content="Ping")],
        workspace_dir="/workspace",
        extra_params={"session_id": "sess-oa-1"},
    )
    resp_oa = await oa_mod.handle_openai_turn(req_oa)
    assert resp_oa.status == "completed"
    tp_trace, tp_span = parse_traceparent(captured_openai_headers.get("traceparent"))
    assert tp_trace == deterministic_trace_id("sess-oa-1", "run-oa-1")
    assert len(recorded_turns) == 1
    assert recorded_turns[0]["trace_id"] == tp_trace
    assert recorded_turns[0]["transport_span_id"] == tp_span

    # 2. Claude SDK runner
    captured_claude_headers: dict[str, str] = {}

    class _FakeMessages:
        async def create(self, **kwargs: Any) -> Any:
            blk = types.SimpleNamespace(type="text", text="Claude reply")
            usage = types.SimpleNamespace(input_tokens=15, output_tokens=9)
            return types.SimpleNamespace(content=[blk], usage=usage)

    class _FakeAsyncAnthropic:
        def __init__(self, **kwargs: Any) -> None:
            captured_claude_headers.update(kwargs.get("default_headers") or {})
            self.messages = _FakeMessages()

    fake_anthropic_pkg = types.ModuleType("anthropic")
    fake_anthropic_pkg.AsyncAnthropic = _FakeAsyncAnthropic  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic_pkg)

    claude_srv_path = REPO_ROOT / "docker/runners/claude-sdk/server.py"
    spec_cl = importlib.util.spec_from_file_location("claude_runner_srv_382", claude_srv_path)
    assert spec_cl and spec_cl.loader
    cl_mod = importlib.util.module_from_spec(spec_cl)
    spec_cl.loader.exec_module(cl_mod)
    monkeypatch.setattr(cl_mod.OTelTraceDispatcher, "from_env", classmethod(lambda cls: _FakeDispatcher()))

    req_cl = AgentTurnRequest(
        run_id="run-cl-1",
        agent_id="claude",
        model="claude-sonnet-4",
        system_prompt="You are helpful.",
        conversation=[ChatMessage(role="user", content="Ping")],
        workspace_dir="/workspace",
        extra_params={"session_id": "sess-cl-1"},
    )
    resp_cl = await cl_mod.handle_claude_turn(req_cl)
    assert resp_cl.status == "completed"
    cl_trace, cl_span = parse_traceparent(captured_claude_headers.get("traceparent"))
    assert cl_trace == deterministic_trace_id("sess-cl-1", "run-cl-1")
    assert len(recorded_turns) == 2
    assert recorded_turns[1]["trace_id"] == cl_trace
    assert recorded_turns[1]["transport_span_id"] == cl_span

