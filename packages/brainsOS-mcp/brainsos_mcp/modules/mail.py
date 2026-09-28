"""brainsos_mcp.modules.mail — RFC-compliant Email capabilities."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register_mail_tools(mcp: FastMCP) -> list[str]:
    """Register email tools onto the FastMCP server."""

    @mcp.tool()
    def send_email(
        to: str,
        subject: str,
        body: str,
        reply_to_id: str = "",
    ) -> str:
        """Send email via mail server."""
        try:
            from brainsos_mail.client import BrainsOSMailClient

            client = BrainsOSMailClient()
            msg_id = client.send_mail(
                to=to,
                subject=subject,
                body=body,
                in_reply_to=reply_to_id if reply_to_id else None,
            )
            return json.dumps({
                "success": True,
                "message_id": msg_id,
                "to": to,
                "subject": subject,
            })
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    @mcp.tool()
    def read_email(query_or_id: str = "", folder: str = "INBOX") -> str:
        """Read email by query or ID."""
        try:
            from brainsos_mail.client import BrainsOSMailClient

            client = BrainsOSMailClient()
            if query_or_id:
                msg = client.read_message(message_id=query_or_id, folder=folder)
                if not msg:
                    msgs = client.search_messages(query=query_or_id, folder=folder, limit=1)
                    msg = msgs[0] if msgs else None
            else:
                msgs = client.fetch_messages(folder=folder, limit=1)
                msg = msgs[0] if msgs else None

            if not msg:
                return json.dumps({"success": False, "error": "No message found"})
            return json.dumps({"success": True, "message": msg})
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    return ["send_email", "read_email"]
