"""Runner Mail Adapter connecting brainsOS agents to brainsOS-runner microservices."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from brainsos_mail.models import ParsedInboundEmail
from brainsos_runner import AgentTurnRequest, ChatMessage, WarmHttpRunnerClient

from brainsos_agent.context import ContextAssembler
from brainsos_agent.models import AgentProfile, OutboundEmail
from brainsos_agent.runtime import AgentRuntime
from brainsos_agent.souls import resolve_soul

logger = logging.getLogger("brainsos_agent.adapters.runner")


class RunnerMailAdapter(AgentRuntime):
    """Stateless HTTP adapter routing inbound email through brainsOS-runner microservices."""

    def __init__(
        self,
        runner_id: str = "hermes-warm",
        endpoint: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.runner_id = runner_id
        raw_endpoint = endpoint or os.getenv("RUNNER_ENDPOINT") or "http://127.0.0.1:8642"
        self.endpoint = raw_endpoint.rstrip("/")
        self.timeout = timeout

    def _assemble_system_prompt_with_working_memory(
        self, profile: AgentProfile, resolved_soul: str | None = None
    ) -> str:
        """Injects persona (SOUL.md) and OKF working memory rules into system prompt."""
        parts: list[str] = []

        persona_text = (resolved_soul or "").strip()
        if not persona_text and profile.soul:
            try:
                persona_text = resolve_soul(profile.soul)
            except Exception:
                persona_text = ""
        if not persona_text and profile.soul_path and profile.soul_path.exists():
            try:
                persona_text = profile.soul_path.read_text(encoding="utf-8").strip()
            except Exception as e:
                logger.warning("Failed to read SOUL.md at %s: %s", profile.soul_path, e)
        if not persona_text:
            persona_text = f"You are {profile.name}, an autonomous AI agent in the brainsOS fleet."
        parts.append(persona_text)

        # Memory guidelines from memory_root/rules
        rules_dir = profile.memory_root / "rules"
        if rules_dir.exists() and rules_dir.is_dir():
            for rule_file in sorted(rules_dir.glob("*.md")):
                try:
                    rule_text = rule_file.read_text(encoding="utf-8").strip()
                    if rule_text.startswith("---"):
                        splits = rule_text.split("---", 2)
                        rule_body = splits[2].strip() if len(splits) >= 3 else rule_text
                    else:
                        rule_body = rule_text
                    if rule_body:
                        parts.append(f"\n### Memory Guideline ({rule_file.stem})\n{rule_body}")
                except Exception as e:
                    logger.debug("Could not read rule file %s: %s", rule_file, e)

        parts.append(
            f"\n### Runtime Environment\n"
            f"- Assigned Identity: {profile.name} <{profile.email}>\n"
            f"- Workspace Root: /workspace (isolated filesystem root)\n"
            f"- Memory Root: /memories (human-auditable Markdown storage)\n"
        )
        return "\n\n".join(parts)

    async def process_message(
        self,
        email: ParsedInboundEmail,
        profile: AgentProfile,
    ) -> OutboundEmail:
        """Executes one turn through the target brainsOS-runner service."""
        system_prompt = self._assemble_system_prompt_with_working_memory(profile)
        historical_turns = ContextAssembler.load_thread_turns(profile.memory_root, email.thread_id)

        conversation: list[ChatMessage] = []
        for t in historical_turns:
            role_val = t.get("role", "user")
            valid_role = role_val if role_val in ("system", "user", "assistant", "tool") else "user"
            content = t.get("content", "")
            conversation.append(ChatMessage(role=valid_role, content=content))  # type: ignore[arg-type]
        conversation.append(ChatMessage(role="user", content=email.clean_body))

        # Record inbound user turn into OKF thread file
        ContextAssembler.record_turn(
            memory_root=profile.memory_root,
            thread_id=email.thread_id,
            subject=email.subject,
            role="user",
            author=email.sender,
            content=email.clean_body,
        )

        run_id = f"mail-{profile.id}-{int(time.time() * 1000)}"
        profile_extras = getattr(profile, "extra_params", None)
        extra_params: dict[str, Any] = dict(profile_extras) if profile_extras else {}
        extra_params["inbound_email_id"] = email.message_id
        extra_params["sender"] = email.sender

        turn_request = AgentTurnRequest(
            run_id=run_id,
            agent_id=profile.id or profile.name,
            model=profile.model,
            system_prompt=system_prompt,
            conversation=conversation,
            workspace_dir=str(profile.workspace_root),
            timeout_sec=int(self.timeout),
            extra_params=extra_params,
        )

        client = WarmHttpRunnerClient(endpoint=self.endpoint, default_timeout_sec=int(self.timeout))
        try:
            response = await client.execute_turn(turn_request)
        finally:
            await client.aclose()

        assistant_reply = response.output_text.strip() if response.status == "completed" else ""
        if not assistant_reply and response.error_message:
            logger.warning("Runner turn failed: %s", response.error_message)
            assistant_reply = f"[Error executing cognitive turn: {response.error_message}]"

        if assistant_reply:
            ContextAssembler.record_turn(
                memory_root=profile.memory_root,
                thread_id=email.thread_id,
                subject=email.subject,
                role="assistant",
                author=profile.email,
                content=assistant_reply,
            )

        clean_subj = email.subject if email.subject.lower().startswith("re:") else f"Re: {email.subject}"

        return OutboundEmail(
            to=email.sender,
            subject=clean_subj,
            body=assistant_reply,
            thread_id=email.thread_id,
            in_reply_to=email.message_id,
            references=email.message_id,
            metadata={
                "model": profile.model,
                "agent_id": profile.id,
                "runner_id": self.runner_id,
                "run_id": run_id,
                "metrics": response.metrics.model_dump() if response.metrics else {},
            },
        )
