"""Unit tests for LiteLLM Lens OTLP tracing, W3C traceparent correlation, and LANGFUSE_ENABLED toggle (Ticket #375)."""

from __future__ import annotations

import asyncio
import dataclasses
import importlib.util
import json
import re
import sys
import types
from pathlib import Path
from typing import Any

import httpx
import pytest
from brainsos_agent import langfuse_trace, lens_trace
from brainsos_agent.langfuse_trace import record_mail_run_trace, thread_trace_id
from brainsos_agent.lens_trace import build_lens_email_run_otlp, record_lens_mail_run_trace

REPO_ROOT = Path(__file__).resolve().parents[3]
SESSION = "mail-bawtford-lens_verify_01"


def _kwargs(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "session_id": SESSION,
        "agent_id": "bawtford",
        "agent_name": "Bawtford",
        "sender": "admin@example.test",
        "subject": "Telemetry check",
        "run_id": "run_375",
        "status": "completed",
        "input_text": "Check current status.",
        "output_text": "All systems nominal.",
        "error": None,
        "usage": {"input_tokens": 24, "output_tokens": 12},
        "started_at": 1_700_000_000.0,
        "ended_at": 1_700_000_012.5,
    }
    base.update(over)
    return base


def _span_attrs(span: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for kv in span.get("attributes", []):
        val = kv["value"]
        if "arrayValue" in val:
            out[kv["key"]] = [v["stringValue"] for v in val["arrayValue"]["values"]]
        else:
            out[kv["key"]] = next(iter(val.values()))
    return out


# ------------------------------------------------------------------ Worker Lens OTLP & LANGFUSE_ENABLED toggle


def test_lens_email_run_otlp_genai_workflow_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRAINSOS_LOCAL_DOMAIN", "dgx.local.brainsos.ai")
    payload = build_lens_email_run_otlp(**_kwargs())
    rs = payload["resourceSpans"][0]
    res_attrs = {kv["key"]: next(iter(kv["value"].values())) for kv in rs["resource"]["attributes"]}
    assert res_attrs["service.name"] == "brainsos-agent-worker"
    assert res_attrs["gen_ai.agent.name"] == "bawtford"
    assert res_attrs["host.name"] == "dgx.local.brainsos.ai"

    spans = rs["scopeSpans"][0]["spans"]
    assert len(spans) == 1
    span = spans[0]
    attrs = _span_attrs(span)
    assert span["traceId"] == thread_trace_id(SESSION)
    assert len(span["spanId"]) == 16
    assert span["name"] == "email-run bawtford: Telemetry check"
    assert span["status"] == {"code": 0}
    assert attrs["gen_ai.operation.name"] == "invoke_workflow"
    assert attrs["gen_ai.agent.name"] == "bawtford"
    assert attrs["gen_ai.conversation.id"] == SESSION
    assert attrs["session.id"] == SESSION
    assert attrs["user.id"] == "admin@example.test"
    assert json.loads(attrs["gen_ai.input.messages"]) == [{"role": "user", "content": "Check current status."}]
    assert json.loads(attrs["gen_ai.output.messages"]) == [{"role": "assistant", "content": "All systems nominal."}]


def test_langfuse_disabled_keeps_lens_worker_trace_active(monkeypatch: pytest.MonkeyPatch) -> None:
    """When LANGFUSE_ENABLED=false, Langfuse is cleanly suppressed while Lens OTLP export stays active."""
    monkeypatch.setenv("LANGFUSE_ENABLED", "false")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    monkeypatch.setenv("LENS_ENABLED", "true")
    monkeypatch.setenv("LENS_OTLP_ENDPOINT", "http://lens.test:4318")
    monkeypatch.setenv("LITELLM_TRACING_KEY", "lens-trace-test-key-375")  # gitleaks:allow

    assert langfuse_trace.is_langfuse_enabled() is False
    assert langfuse_trace.langfuse_settings() is None
    assert lens_trace.is_lens_enabled() is True
    assert lens_trace.lens_settings() == ("http://lens.test:4318/v1/traces", "lens-trace-test-key-375")

    calls: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append({"url": str(request.url), "headers": dict(request.headers), "json": json.loads(request.content)})
        return httpx.Response(200, json={"partialSuccess": {}})

    async def run() -> tuple[bool, bool]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            lf_ok = await record_mail_run_trace(http_client=client, **_kwargs())
            lens_ok = await record_lens_mail_run_trace(http_client=client, **_kwargs())
            return lf_ok, lens_ok

    lf_ok, lens_ok = asyncio.run(run())
    assert lf_ok is False
    assert lens_ok is True
    assert len(calls) == 1
    assert calls[0]["url"] == "http://lens.test:4318/v1/traces"
    assert calls[0]["headers"]["authorization"] == "Bearer lens-trace-test-key-375"
    span = calls[0]["json"]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    assert span["traceId"] == thread_trace_id(SESSION)


# ------------------------------------------------------------------ Hermes provider traceparent + Lens OTLP plugin


def test_hermes_provider_plugin_injects_valid_w3c_traceparent(monkeypatch: pytest.MonkeyPatch) -> None:
    registry: dict[str, Any] = {}

    @dataclasses.dataclass
    class FakeProfile:
        name: str = "custom"

        def build_extra_body(self, *, session_id: str | None = None, **context: Any) -> dict[str, Any]:
            return {}

    registry["custom"] = FakeProfile()
    fake_providers = types.ModuleType("providers")
    fake_providers._REGISTRY = registry  # type: ignore[attr-defined]
    fake_providers.register_provider = lambda p: registry.__setitem__(p.name, p)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "providers", fake_providers)
    monkeypatch.setenv("BAWTFORD_LITELLM_KEY", "sk-virt-bawt-test")

    plugin = REPO_ROOT / "docker/hermes/plugins/model-providers/brainsos-litellm-session/__init__.py"
    spec = importlib.util.spec_from_file_location("brainsos_litellm_session_375", plugin)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    _, top_a = registry["custom"].build_api_kwargs_extras(session_id=SESSION)
    _, top_b = registry["custom"].build_api_kwargs_extras(session_id=SESSION)
    tp_a = top_a["extra_headers"]["traceparent"]
    tp_b = top_b["extra_headers"]["traceparent"]

    match_a = re.match(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-01$", tp_a)
    match_b = re.match(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-01$", tp_b)
    assert match_a and match_b
    # Same deterministic session trace_id, distinct per-attempt gateway transport span_id.
    assert match_a.group(1) == thread_trace_id(SESSION)
    assert match_b.group(1) == thread_trace_id(SESSION)
    assert match_a.group(2) != match_b.group(2)


def test_hermes_lens_otel_multi_step_tool_turn_with_langfuse_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify Hermes observability plugin emits Lens OTLP invoke_agent + chat + gateway.request + execute_tool spans
    even when LANGFUSE_ENABLED=false and no Langfuse SDK is installed."""
    monkeypatch.setenv("LANGFUSE_ENABLED", "false")
    monkeypatch.setenv("LENS_ENABLED", "true")
    monkeypatch.setenv("LENS_OTLP_ENDPOINT", "http://lens.internal:4318")
    monkeypatch.setenv("LITELLM_TRACING_KEY", "lens-trace-hermes-375")  # gitleaks:allow
    monkeypatch.setenv("BRAINSOS_LOCAL_DOMAIN", "dgx.local.brainsos.ai")

    plugin_init = REPO_ROOT / "docker/hermes/plugins/observability/langfuse/__init__.py"
    sys.modules.pop("_brainsos_hermes_lens_otel", None)
    spec = importlib.util.spec_from_file_location("hermes_langfuse_plugin_375", plugin_init)
    assert spec and spec.loader
    plugin_mod = importlib.util.module_from_spec(spec)
    sys.modules["hermes_langfuse_plugin_375"] = plugin_mod
    spec.loader.exec_module(plugin_mod)

    lens_mod = plugin_mod._lens_otel
    exported: list[tuple[str, str, dict[str, Any]]] = []

    def _capture_transport(url: str, token: str, payload: dict[str, Any]) -> bool:
        exported.append((url, token, payload))
        return True

    lens_mod.set_custom_transport(_capture_transport)

    try:
        trace_id = thread_trace_id(SESSION)
        tp_span_1 = "1111222233334444"
        tp_span_2 = "5555666677778888"

        class FakeFn:
            def __init__(self, name: str, arguments: str) -> None:
                self.name = name
                self.arguments = arguments

        class FakeToolCall:
            def __init__(self, tc_id: str, name: str, arguments: str) -> None:
                self.id = tc_id
                self.type = "function"
                self.function = FakeFn(name, arguments)

        class FakeAssistantMsg:
            def __init__(self, content: str | None, tool_calls: list[Any] | None = None) -> None:
                self.content = content
                self.reasoning = None
                self.tool_calls = tool_calls or []

        # 1. Step 1 LLM request -> returns tool call
        plugin_mod.on_pre_llm_request(
            task_id=SESSION,
            session_id=SESSION,
            turn_id="turn_1",
            api_request_id="req_1",
            api_call_count=1,
            model="brainsos-core-reasoner",
            base_url="http://litellm:4000/v1",
            request_messages=[{"role": "user", "content": "List files in /memories"}],
            request={
                "body": {
                    "model": "brainsos-core-reasoner",
                    "extra_headers": {"traceparent": f"00-{trace_id}-{tp_span_1}-01"},
                }
            },
            started_at=1_700_000_001.0,
        )
        plugin_mod.on_post_llm_call(
            task_id=SESSION,
            session_id=SESSION,
            turn_id="turn_1",
            api_request_id="req_1",
            api_call_count=1,
            model="brainsos-core-reasoner",
            response_model="llama3.2:3b",
            finish_reason="tool_calls",
            usage={"input_tokens": 120, "output_tokens": 25},
            assistant_message=FakeAssistantMsg(
                None,
                [FakeToolCall("call_abc", "terminal", '{"command": "ls /memories"}')],
            ),
            started_at=1_700_000_001.0,
            ended_at=1_700_000_002.0,
        )

        # 2. Tool execution
        plugin_mod.on_pre_tool_call(
            task_id=SESSION,
            session_id=SESSION,
            turn_id="turn_1",
            tool_name="terminal",
            tool_call_id="call_abc",
            args={"command": "ls /memories"},
        )
        plugin_mod.on_post_tool_call(
            task_id=SESSION,
            session_id=SESSION,
            turn_id="turn_1",
            tool_name="terminal",
            tool_call_id="call_abc",
            args={"command": "ls /memories"},
            result={"stdout": "README.md\nnotes.md\n", "exit_code": 0},
        )

        # 3. Step 2 LLM request -> final assistant answer
        plugin_mod.on_pre_llm_request(
            task_id=SESSION,
            session_id=SESSION,
            turn_id="turn_1",
            api_request_id="req_2",
            api_call_count=2,
            model="brainsos-core-reasoner",
            base_url="http://litellm:4000/v1",
            request_messages=[
                {"role": "user", "content": "List files in /memories"},
                {"role": "tool", "tool_call_id": "call_abc", "content": '{"stdout": "README.md\\nnotes.md\\n"}'},
            ],
            request={
                "body": {
                    "model": "brainsos-core-reasoner",
                    "extra_headers": {"traceparent": f"00-{trace_id}-{tp_span_2}-01"},
                }
            },
            started_at=1_700_000_003.0,
        )
        plugin_mod.on_post_llm_call(
            task_id=SESSION,
            session_id=SESSION,
            turn_id="turn_1",
            api_request_id="req_2",
            api_call_count=2,
            model="brainsos-core-reasoner",
            response_model="llama3.2:3b",
            finish_reason="stop",
            usage={"input_tokens": 160, "output_tokens": 18},
            assistant_message=FakeAssistantMsg("Found README.md and notes.md in /memories."),
            started_at=1_700_000_003.0,
            ended_at=1_700_000_004.0,
        )
    finally:
        lens_mod.set_custom_transport(None)

    # Collect all exported spans grouped by instrumentation scope
    hermes_spans: list[dict[str, Any]] = []
    gateway_spans: list[dict[str, Any]] = []
    for url, token, payload in exported:
        assert url == "http://lens.internal:4318/v1/traces"
        assert token == "lens-trace-hermes-375"  # gitleaks:allow
        for scope_block in payload["resourceSpans"][0]["scopeSpans"]:
            scope_name = scope_block["scope"]["name"]
            if scope_name == "hermes-otel-plugin":
                hermes_spans.extend(scope_block["spans"])
            elif scope_name == "litellm.gateway.client":
                gateway_spans.extend(scope_block["spans"])

    ops = [_span_attrs(s).get("gen_ai.operation.name") for s in hermes_spans]
    assert ops.count("chat") == 2
    assert ops.count("execute_tool") == 1
    assert ops.count("invoke_agent") == 1
    assert len(gateway_spans) == 2

    root_span = next(s for s in hermes_spans if _span_attrs(s).get("gen_ai.operation.name") == "invoke_agent")
    chat_spans = [s for s in hermes_spans if _span_attrs(s).get("gen_ai.operation.name") == "chat"]
    tool_span = next(s for s in hermes_spans if _span_attrs(s).get("gen_ai.operation.name") == "execute_tool")

    # Verify trace & parent hierarchy
    for s in (*hermes_spans, *gateway_spans):
        assert s["traceId"] == trace_id
    for cs in chat_spans:
        assert cs["parentSpanId"] == root_span["spanId"]
    assert tool_span["parentSpanId"] == root_span["spanId"]

    # Verify gateway.request transport spans carry exact traceparent spanIds parented to each chat span
    assert {gs["spanId"] for gs in gateway_spans} == {tp_span_1, tp_span_2}
    assert {gs["parentSpanId"] for gs in gateway_spans} == {cs["spanId"] for cs in chat_spans}
    for gs in gateway_spans:
        gw_attrs = _span_attrs(gs)
        assert gw_attrs["litellm.gateway.attempt"] == "true"
        assert gw_attrs["http.request.method"] == "POST"

    # Verify tool & root span payloads
    tool_attrs = _span_attrs(tool_span)
    assert tool_attrs["gen_ai.tool.name"] == "terminal"
    assert "ls /memories" in tool_attrs["gen_ai.tool.call.arguments"]
    assert "README.md" in tool_attrs["gen_ai.tool.call.result"]

    root_attrs = _span_attrs(root_span)
    assert root_attrs["gen_ai.agent.name"] == "bawtford"
    assert "Found README.md and notes.md" in root_attrs["gen_ai.output.messages"]
