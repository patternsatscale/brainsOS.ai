"""Auto-Responder / Ping Agent Runtime Adapter for brainsOS."""

from __future__ import annotations

import logging
from typing import Any

from brainsos_mail.models import ParsedInboundEmail
from brainsos_agent.context import ContextAssembler
from brainsos_agent.models import AgentProfile, OutboundEmail
from brainsos_agent.runtime import AgentRuntime

logger = logging.getLogger("brainsos_agent.autoresponder")


class AutoResponderAdapter(AgentRuntime):
    """Deterministic auto-responder adapter requiring zero LLM inference.

    Ideal for health checks, round-trip integration testing, and latency verification.
    """

    def __init__(self, greeting_prefix: str = "Hello!") -> None:
        self.greeting_prefix = greeting_prefix

    async def process_message(
        self,
        email: ParsedInboundEmail,
        profile: AgentProfile,
    ) -> OutboundEmail:
        """Generates deterministic acknowledgement and persists turn in OKF memory."""
        # 1. Record inbound turn in OKF thread dialogue
        ContextAssembler.record_turn(
            memory_root=profile.memory_root,
            thread_id=email.thread_id,
            subject=email.subject,
            role="user",
            author=email.sender,
            content=email.clean_body,
        )

        clean_subj = email.subject if email.subject.lower().startswith("re:") else f"Re: {email.subject}"
        reply_body = (
            f"{self.greeting_prefix}\n\n"
            f"I received your email regarding '{email.subject}'.\n\n"
            f"--- Received Message ---\n"
            f"{email.clean_body}\n"
            f"------------------------\n\n"
            f"Agent: {profile.name} <{profile.email}>\n"
            f"Thread ID: {email.thread_id}\n"
            f"Status: Auto-responder ACK (deterministic, zero LLM inference)\n"
        )

        # 2. Record auto-responder turn in OKF memory
        ContextAssembler.record_turn(
            memory_root=profile.memory_root,
            thread_id=email.thread_id,
            subject=email.subject,
            role="assistant",
            author=profile.email,
            content=reply_body,
        )

        return OutboundEmail(
            to=email.sender,
            subject=clean_subj,
            body=reply_body,
            thread_id=email.thread_id,
            in_reply_to=email.message_id,
            references=email.message_id,
            metadata={
                "adapter": "autoresponder",
                "agent_id": profile.id,
                "model": "none/deterministic",
            },
        )
