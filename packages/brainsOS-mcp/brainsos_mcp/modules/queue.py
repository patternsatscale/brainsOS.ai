"""brainsos_mcp.modules.queue — Asynchronous Work Queue capabilities."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

_MAX_PAYLOAD_BYTES = 16_384
_MAX_PAYLOAD_DEPTH = 64

_ALLOWED_TASK_TYPES = frozenset(
    {
        "mcp_sample_task",
        "agent_note",
        "agent_followup",
        "research_task",
        "web_task",
        "summary_task",
    }
)

_FORBIDDEN_PAYLOAD_KEYS = frozenset(
    {
        "raw_mime",
        "spool_path",
        "pending_reply",
        "hermes_run_id",
        "hermes_run_submitted_at",
        "queue",
    }
)

_SCOPE_KEYS = frozenset({"tenant_id", "agent_id", "partition_key"})
_CANONICAL_OVERRIDE_KEYS = _SCOPE_KEYS | frozenset({"task_type"})


def _find_forbidden_key(obj: Any) -> str | None:
    stack: list[tuple[Any, int]] = [(obj, 0)]
    while stack:
        current, depth = stack.pop()
        if depth > _MAX_PAYLOAD_DEPTH:
            raise ValueError(f"payload_json exceeds maximum nesting depth ({_MAX_PAYLOAD_DEPTH})")
        if isinstance(current, dict):
            for k, v in current.items():
                key_lower = str(k).strip().lower()
                if key_lower in _FORBIDDEN_PAYLOAD_KEYS:
                    return str(k)
                if isinstance(v, (dict, list)):
                    stack.append((v, depth + 1))
        elif isinstance(current, list):
            for item in current:
                if isinstance(item, (dict, list)):
                    stack.append((item, depth + 1))
    return None


def register_queue_tools(mcp: FastMCP) -> list[str]:
    """Register asynchronous work queue tools onto the FastMCP server."""
    from brainsos_queue.queue import get_queue

    @mcp.tool()
    async def enqueue_task(task_type: str, payload_json: str = "{}") -> str:
        """Enqueue task to work queue."""
        try:
            normalized_type = (task_type or "").strip()
            if normalized_type not in _ALLOWED_TASK_TYPES:
                return json.dumps(
                    {
                        "success": False,
                        "error": f"Task type '{normalized_type}' is not permitted",
                    }
                )

            if not isinstance(payload_json, str):
                return json.dumps(
                    {"success": False, "error": "payload_json must be a JSON string"}
                )

            if len(payload_json.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
                return json.dumps(
                    {
                        "success": False,
                        "error": f"payload_json exceeds maximum size ({_MAX_PAYLOAD_BYTES} bytes)",
                    }
                )

            payload = json.loads(payload_json)
            if not isinstance(payload, dict):
                return json.dumps(
                    {"success": False, "error": "payload_json must decode to a JSON object"}
                )

            forbidden_key = _find_forbidden_key(payload)
            if forbidden_key is not None:
                return json.dumps(
                    {
                        "success": False,
                        "error": f"Forbidden payload key: '{forbidden_key}'",
                    }
                )

            for raw_key in payload:
                norm_key = str(raw_key).strip().lower()
                if norm_key in _CANONICAL_OVERRIDE_KEYS and raw_key != norm_key:
                    return json.dumps(
                        {
                            "success": False,
                            "error": f"Non-canonical key '{raw_key}' is forbidden",
                        }
                    )

            active_agent = (os.getenv("BRAINSOS_AGENT_ID") or "").strip()
            if active_agent:
                for scope_key in ("tenant_id", "agent_id", "partition_key"):
                    if scope_key in payload:
                        val = str(payload[scope_key]).strip()
                        if val != active_agent:
                            return json.dumps(
                                {
                                    "success": False,
                                    "error": f"Cross-tenant {scope_key} '{val}' is forbidden",
                                }
                            )
                payload["tenant_id"] = active_agent
                payload["agent_id"] = active_agent

            payload["task_type"] = normalized_type
            queue = get_queue()
            task = await queue.enqueue(
                payload=payload,
                partition_key=active_agent or None,
            )
            return json.dumps(
                {
                    "success": True,
                    "task_id": task.id,
                    "queue": task.queue,
                    "status": task.status.value,
                }
            )
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    @mcp.tool()
    async def get_task_status(task_id: str) -> str:
        """Get queued task status."""
        try:
            queue = get_queue()
            task = await queue.get_task(task_id)
            if not task:
                return json.dumps({"success": False, "error": f"Task '{task_id}' not found"})

            active_agent = (os.getenv("BRAINSOS_AGENT_ID") or "").strip()
            if active_agent:
                task_payload = task.payload if isinstance(task.payload, dict) else {}
                task_tenant = (
                    task.partition_key
                    or task_payload.get("tenant_id")
                    or task_payload.get("agent_id")
                )
                if task_tenant != active_agent:
                    return json.dumps(
                        {"success": False, "error": f"Task '{task_id}' not found"}
                    )

            return json.dumps(
                {
                    "success": True,
                    "task_id": task.id,
                    "status": task.status.value,
                    "result": task.result,
                    "error": task.error,
                }
            )
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    return ["enqueue_task", "get_task_status"]
