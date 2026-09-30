"""Hermes Mail Adapter for brainsOS Shared Stateless Agent Runner."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import httpx
from brainsos_mail.models import ParsedInboundEmail

from brainsos_agent.context import ContextAssembler
from brainsos_agent.models import AgentProfile, OutboundEmail
from brainsos_agent.runtime import AgentRuntime
from brainsos_agent.souls import resolve_soul

logger = logging.getLogger("brainsos_agent.hermes")


class WorkspaceBoundaryViolation(ValueError):
    """Raised when a tool execution or path escapes the agent's isolated workspace partition."""

    pass


class HermesMailAdapter(AgentRuntime):
    """Stateless HTTP adapter routing inbound email through the shared warm Hermes runner."""

    def __init__(
        self,
        runner_url: str | None = None,
        timeout: float = 60.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.runner_url = runner_url or os.getenv("HERMES_RUNNER_URL", "http://127.0.0.1:8642/v1")
        self.timeout = timeout
        self._client = http_client

    def validate_workspace_path(self, target_path: str | Path, profile: AgentProfile) -> Path:
        """Enforces that file tool executions cannot read or mutate files outside workspace_root."""
        ws_root = profile.workspace_root.resolve()
        resolved_target = (
            (ws_root / target_path).resolve() if not Path(target_path).is_absolute() else Path(target_path).resolve()
        )
        try:
            resolved_target.relative_to(ws_root)
        except ValueError:
            raise WorkspaceBoundaryViolation(
                f"Workspace isolation violation: Path '{target_path}' resolves outside agent workspace root '{ws_root}'"
            )
        return resolved_target

    def _assemble_system_prompt_with_working_memory(
        self, profile: AgentProfile, resolved_soul: str | None = None
    ) -> str:
        """Injects persona (SOUL.md) and OKF working memory rules into system prompt."""
        parts: list[str] = []

        # 1. Base Persona from SOUL.md / SoulResolver
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

        # 2. Inject OKF working memory rules / guidelines from memory_root/rules
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

        # 3. Add workspace path guideline to keep tools isolated (Rule 7 compliant)
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
        resolved_soul: str | None = None,
    ) -> OutboundEmail:
        """Executes one turn through the shared Hermes runner in stateless API mode."""
        # 1. System Prompt with Persona & OKF Working Memory
        system_prompt = self._assemble_system_prompt_with_working_memory(profile, resolved_soul=resolved_soul)

        # 2. Historical Dialogue Turns & Current Inbound Email from pure OKF memory
        historical_turns = ContextAssembler.load_thread_turns(profile.memory_root, email.thread_id)

        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        messages.extend(historical_turns)
        messages.append({"role": "user", "content": email.clean_body})

        # Record inbound user turn into OKF thread file
        ContextAssembler.record_turn(
            memory_root=profile.memory_root,
            thread_id=email.thread_id,
            subject=email.subject,
            role="user",
            author=email.sender,
            content=email.clean_body,
        )

        # 3. Stateless API dispatch to Hermes (POST /v1/chat/completions)
        runner_url = (self.runner_url or "http://127.0.0.1:8642/v1").rstrip("/")
        endpoint = f"{runner_url}/chat/completions"
        request_payload = {
            "model": profile.model,
            "messages": messages,
            "temperature": 0.7,
            "stream": False,
            "extra_body": {
                "agent_id": profile.id or profile.name,
                "workspace_root": str(profile.workspace_root),
                "memory_root": str(profile.memory_root),
                "mcp_modules": profile.mcp_modules,
            },
        }

        headers = {
            "Content-Type": "application/json",
            "X-BrainsOS-Agent": profile.id or profile.name,
        }

        # Issue request via httpx
        if self._client:
            client = self._client
            should_close = False
        else:
            client = httpx.AsyncClient(timeout=self.timeout)
            should_close = True

        try:
            response = await client.post(endpoint, json=request_payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        finally:
            if should_close:
                await client.aclose()

        # 4. Extract reply and tool calls
        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})
        assistant_reply = str(message.get("content") or "").strip()
        tool_calls = message.get("tool_calls", [])

        # Record assistant reply turn into OKF memory
        if assistant_reply:
            ContextAssembler.record_turn(
                memory_root=profile.memory_root,
                thread_id=email.thread_id,
                subject=email.subject,
                role="assistant",
                author=profile.email,
                content=assistant_reply,
            )

        # Clean subject line
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
                "tool_calls": tool_calls,
                "usage": data.get("usage", {}),
            },
        )
