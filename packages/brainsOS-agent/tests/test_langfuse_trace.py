"""Tests for the worker-side Langfuse email-run span (Ticket #299)."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

import httpx
import pytest
from brainsos_agent import langfuse_trace
from brainsos_agent.langfuse_trace import build_email_run_otlp, record_mail_run_trace, thread_trace_id

SESSION = "mail-bawtford-abc_dgx_local"


def _kwargs(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "session_id": SESSION,
        "agent_id": "bawtford",
        "agent_name": "Bawtford",
        "sender": "admin@example.test",
        "subject": "Hello",
        "run_id": "run_123",
        "status": "completed",
        "input_text": "Please reply.",
        "output_text": "Done.",
        "error": None,
        "usage": {"input_tokens": 10},
        "started_at": 1_700_000_000.0,
        "ended_at": 1_700_000_042.5,
    }
    base.update(over)
    return base


def _span(payload: dict[str, Any]) -> dict[str, Any]:
    spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
    assert len(spans) == 1
    return spans[0]


def _attrs(span: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for kv in span["attributes"]:
        value = kv["value"]
        if "arrayValue" in value:
            out[kv["key"]] = [v["stringValue"] for v in value["arrayValue"]["values"]]
        else:
            out[kv["key"]] = next(iter(value.values()))
    return out


# ------------------------------------------------------------------ trace id


def test_thread_trace_id_matches_hermes_seed() -> None:
    expected = hashlib.sha256(f"{SESSION}::{SESSION}".encode()).digest()[:16].hex()
    assert thread_trace_id(SESSION) == expected
    assert len(expected) == 32


def test_thread_trace_id_matches_langfuse_sdk_when_available() -> None:
    langfuse = pytest.importorskip("langfuse")
    assert thread_trace_id(SESSION) == langfuse.Langfuse.create_trace_id(seed=f"{SESSION}::{SESSION}")


def test_same_thread_same_trace_different_threads_differ() -> None:
    assert thread_trace_id(SESSION) == thread_trace_id(SESSION)
    assert thread_trace_id(SESSION) != thread_trace_id("mail-bawtford-other")


# ------------------------------------------------------------------ payload shape


def test_completed_span_shape() -> None:
    span = _span(build_email_run_otlp(**_kwargs()))
    attrs = _attrs(span)
    assert span["traceId"] == thread_trace_id(SESSION)
    assert len(span["spanId"]) == 16
    assert "parentSpanId" not in span
    assert span["name"] == "email-run Bawtford"
    assert span["startTimeUnixNano"] == str(1_700_000_000 * 10**9)
    assert span["endTimeUnixNano"] == str(1_700_000_042_500_000_000)
    assert span["status"] == {"code": 0}
    assert attrs["session.id"] == SESSION
    assert attrs["user.id"] == "admin@example.test"
    assert attrs["langfuse.trace.tags"] == ["brainsos-mail", "agent:bawtford", "status:completed"]
    assert attrs["langfuse.observation.type"] == "span"
    assert attrs["langfuse.observation.level"] == "DEFAULT"
    assert attrs["langfuse.observation.input"] == "Please reply."
    assert attrs["langfuse.observation.output"] == "Done."
    assert "langfuse.observation.status_message" not in attrs


def test_io_recorded_once_not_at_trace_level() -> None:
    attrs = _attrs(_span(build_email_run_otlp(**_kwargs())))
    assert "langfuse.trace.input" not in attrs
    assert "langfuse.trace.output" not in attrs
    assert "langfuse.trace.name" not in attrs  # never rename the Hermes thread trace


def test_failed_span_is_error_level() -> None:
    span = _span(build_email_run_otlp(**_kwargs(status="failed", error="boom", output_text="Sorry")))
    attrs = _attrs(span)
    assert attrs["langfuse.observation.level"] == "ERROR"
    assert attrs["langfuse.observation.status_message"] == "boom"
    assert span["status"] == {"code": 2, "message": "boom"}
    assert "status:failed" in attrs["langfuse.trace.tags"]


def test_long_text_truncated_and_missing_times_default() -> None:
    span = _span(build_email_run_otlp(**_kwargs(input_text="x" * 9000, started_at=None, ended_at=None)))
    attrs = _attrs(span)
    assert attrs["langfuse.observation.input"].endswith("…[truncated]")
    assert span["startTimeUnixNano"] == span["endTimeUnixNano"]


# ------------------------------------------------------------------ export


def test_record_posts_otlp_with_v4_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    monkeypatch.setenv("BRAINSOS_LANGFUSE_URL", "http://langfuse.test")
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        seen["body"] = request.content
        return httpx.Response(200, json={})

    async def run() -> bool:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await record_mail_run_trace(http_client=client, **_kwargs())

    assert asyncio.run(run()) is True
    assert seen["url"] == "http://langfuse.test/api/public/otel/v1/traces"
    assert seen["headers"]["x-langfuse-ingestion-version"] == "4"
    assert seen["headers"]["authorization"] == "Basic " + base64.b64encode(b"pk-lf-test:sk-lf-test").decode()
    assert b"resourceSpans" in seen["body"]
    assert "x-langfuse-sdk-name" not in seen["headers"]


def test_record_never_raises_and_reports_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    async def run() -> bool:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await record_mail_run_trace(http_client=client, **_kwargs())

    assert asyncio.run(run()) is False


def test_record_disabled_without_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "")
    assert langfuse_trace.langfuse_settings() is None
    assert asyncio.run(record_mail_run_trace(**_kwargs())) is False


# ------------------------------------------------------------------ Hermes provider plugin


def test_hermes_provider_plugin_sets_no_log(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Hermes -> LiteLLM provider plugin must send ``no-log`` so LiteLLM skips Langfuse."""
    import dataclasses

    registry: dict[str, Any] = {}

    @dataclasses.dataclass
    class FakeProfile:
        name: str = "custom"

        def build_extra_body(self, *, session_id: str | None = None, **context: Any) -> dict[str, Any]:
            return {"metadata": {"existing": True}}

    registry["custom"] = FakeProfile()
    fake_providers = types.ModuleType("providers")
    fake_providers._REGISTRY = registry  # type: ignore[attr-defined]
    fake_providers.register_provider = lambda p: registry.__setitem__(p.name, p)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "providers", fake_providers)

    plugin = (
        Path(__file__).resolve().parents[3]
        / "docker/hermes/plugins/model-providers/brainsos-litellm-session/__init__.py"
    )
    spec = importlib.util.spec_from_file_location("brainsos_litellm_session_test", plugin)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    body = registry["custom"].build_extra_body(session_id="mail-x-y")
    assert body["no-log"] is True
    assert body["metadata"]["tags"] == ["hermes", "brainsos"]
    assert body["metadata"]["existing"] is True
    assert "session_id" not in body["metadata"]
