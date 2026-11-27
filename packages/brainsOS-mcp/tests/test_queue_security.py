"""Security unit tests for brainsos_mcp.modules.queue (#401 F21)."""

from __future__ import annotations

import json

import pytest
from brainsos_mcp.modules.queue import register_queue_tools
from brainsos_queue.queue import clear_registry


class _FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self):
        def _dec(fn):
            self.tools[fn.__name__] = fn
            return fn

        return _dec


@pytest.fixture(autouse=True)
def _reset_queue_registry():
    clear_registry()
    yield
    clear_registry()


@pytest.mark.asyncio
async def test_enqueue_task_rejects_disallowed_task_types(monkeypatch):
    fm = _FakeMCP()
    register_queue_tools(fm)
    enqueue = fm.tools["enqueue_task"]
    monkeypatch.setenv("BRAINSOS_AGENT_ID", "alice")

    for bad_type in ("inbound_email", "inbound_emails", "system_exec", "", "admin_override"):
        res = json.loads(await enqueue(bad_type, json.dumps({"note": "hi"})))
        assert res["success"] is False


@pytest.mark.asyncio
async def test_enqueue_task_rejects_oversized_and_non_dict_payloads(monkeypatch):
    fm = _FakeMCP()
    register_queue_tools(fm)
    enqueue = fm.tools["enqueue_task"]
    monkeypatch.setenv("BRAINSOS_AGENT_ID", "alice")

    oversized = json.dumps({"note": "x" * 20_000})
    res_big = json.loads(await enqueue("mcp_sample_task", oversized))
    assert res_big["success"] is False

    res_list = json.loads(await enqueue("mcp_sample_task", "[1, 2, 3]"))
    assert res_list["success"] is False


@pytest.mark.asyncio
async def test_enqueue_task_rejects_forbidden_internal_keys(monkeypatch):
    fm = _FakeMCP()
    register_queue_tools(fm)
    enqueue = fm.tools["enqueue_task"]
    monkeypatch.setenv("BRAINSOS_AGENT_ID", "alice")

    for bad_key in ("raw_mime", "spool_path", "pending_reply", "hermes_run_id", "queue"):
        res = json.loads(await enqueue("agent_note", json.dumps({bad_key: "evil"})))
        assert res["success"] is False
        nested = json.loads(await enqueue("agent_note", json.dumps({"outer": {bad_key: "evil"}})))
        assert nested["success"] is False


@pytest.mark.asyncio
async def test_enqueue_task_and_get_task_status_enforce_tenant_isolation(monkeypatch):
    fm = _FakeMCP()
    register_queue_tools(fm)
    enqueue = fm.tools["enqueue_task"]
    get_status = fm.tools["get_task_status"]

    monkeypatch.setenv("BRAINSOS_AGENT_ID", "alice")
    cross = json.loads(await enqueue("agent_note", json.dumps({"tenant_id": "bob", "note": "hi"})))
    assert cross["success"] is False

    cross_agent = json.loads(await enqueue("agent_note", json.dumps({"agent_id": "bob"})))
    assert cross_agent["success"] is False

    ok = json.loads(await enqueue("agent_note", json.dumps({"note": "alice task"})))
    assert ok["success"] is True
    task_id = ok["task_id"]

    status_alice = json.loads(await get_status(task_id))
    assert status_alice["success"] is True

    monkeypatch.setenv("BRAINSOS_AGENT_ID", "bob")
    status_bob = json.loads(await get_status(task_id))
    assert status_bob["success"] is False


@pytest.mark.asyncio
async def test_enqueue_task_rejects_noncanonical_scope_override_keys_and_deep_nesting(monkeypatch):
    fm = _FakeMCP()
    register_queue_tools(fm)
    enqueue = fm.tools["enqueue_task"]
    monkeypatch.setenv("BRAINSOS_AGENT_ID", "alice")

    for bad_key in ("TENANT_ID", "Tenant_Id", "  agent_id  ", "PARTITION_KEY", "TASK_TYPE"):
        res = json.loads(await enqueue("agent_note", json.dumps({bad_key: "bob"})))
        assert res["success"] is False, f"Expected non-canonical key {bad_key!r} to be rejected"

    # Deeply nested JSON under 16 KB must fail cleanly via bounded depth without RecursionError
    deep_payload = ("[" * 200) + "{}" + ("]" * 200)
    deep_obj_json = json.dumps({"nested": json.loads(deep_payload)})
    assert len(deep_obj_json.encode("utf-8")) < 16_384
    deep_res = json.loads(await enqueue("agent_note", deep_obj_json))
    assert deep_res["success"] is False
    assert "nesting depth" in deep_res["error"]
