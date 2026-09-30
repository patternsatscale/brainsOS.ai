"""brainsos_mcp.modules.queue — Asynchronous Work Queue capabilities."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register_queue_tools(mcp: FastMCP) -> list[str]:
    """Register asynchronous work queue tools onto the FastMCP server."""
    from brainsos_queue.queue import get_queue

    @mcp.tool()
    async def enqueue_task(task_type: str, payload_json: str = "{}") -> str:
        """Enqueue task to work queue."""
        try:
            payload: dict[str, Any] = json.loads(payload_json) if isinstance(payload_json, str) else payload_json
            payload["task_type"] = task_type
            queue = get_queue()
            task = await queue.enqueue(payload=payload)
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
