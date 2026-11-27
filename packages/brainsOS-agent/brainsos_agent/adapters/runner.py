"""Runner Mail Adapter connecting brainsOS agents to brainsOS-runner microservices."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from brainsos_mail.models import ParsedInboundEmail
from brainsos_runner import (
    AgentTurnRequest,
    ChatMessage,
    EphemeralDockerRunnerClient,
    WarmHttpRunnerClient,
)

from brainsos_agent.context import ContextAssembler
from brainsos_agent.models import AgentProfile, OutboundEmail
from brainsos_agent.runtime import AgentRuntime
from brainsos_agent.souls import resolve_soul  # noqa: F401

logger = logging.getLogger("brainsos_agent.adapters.runner")

_DEFAULT_EPHEMERAL_IMAGES = {
    "hermes-ephemeral": "brainsos-runner-hermes:latest",
    "openai-ephemeral": "brainsos-runner-openai:latest",
    "claude-ephemeral": "brainsos-runner-claude:latest",
}


class RunnerMailAdapter(AgentRuntime):
    """Adapter routing inbound email through ephemeral per-tenant Docker or warm HTTP runners."""

    def __init__(
        self,
        runner_id: str = "hermes-warm",
        endpoint: str | None = None,
        timeout: float = 60.0,
        *,
        ephemeral: bool | None = None,
        image: str | None = None,
        memory_limit: str | None = None,
        cpu_limit: str | None = None,
        command: list[str] | None = None,
    ) -> None:
        self.runner_id = runner_id
        raw_endpoint = endpoint or os.getenv("RUNNER_ENDPOINT") or "http://127.0.0.1:8642"
        self.endpoint = raw_endpoint.rstrip("/")
        self.timeout = timeout
        if ephemeral is not None:
            self.ephemeral = bool(ephemeral)
        elif runner_id.endswith("-ephemeral"):
            self.ephemeral = True
        elif endpoint is not None:
            self.ephemeral = False
        else:
            self.ephemeral = os.getenv("BRAINSOS_EPHEMERAL_RUNNERS", "").strip().lower() in ("1", "true", "yes")
        self.image = image or _DEFAULT_EPHEMERAL_IMAGES.get(
            runner_id,
            "brainsos-runner-claude:latest"
            if "claude" in runner_id
            else ("brainsos-runner-openai:latest" if "openai" in runner_id else "brainsos-runner-hermes:latest"),
        )
        self.memory_limit = memory_limit or "2g"
        self.cpu_limit = cpu_limit or "2.0"
        self.command = list(command) if command is not None else ["python3", "/app/server.py"]

    def _assemble_system_prompt_with_working_memory(
        self, profile: AgentProfile, resolved_soul: str | None = None
    ) -> str:
        """Injects global directives, persona (SOUL.md), OKF memory rules, and channel directives into system prompt."""
        from brainsos_agent.prompts import assemble_system_prompt

        return assemble_system_prompt(profile, resolved_soul=resolved_soul, channel="email")

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
        if profile.virtual_key_env:
            extra_params.setdefault("virtual_key_env", profile.virtual_key_env)
        extra_params.setdefault("github_allowed_repos", list(profile.github_allowed_repos))

        turn_request = AgentTurnRequest(
            run_id=run_id,
            agent_id=profile.id or profile.name,
            model=profile.model,
            system_prompt=system_prompt,
            conversation=conversation,
            workspace_dir=str(profile.workspace_root),
            memory_dir=str(profile.memory_root),
            timeout_sec=int(self.timeout),
            extra_params=extra_params,
        )

        if self.ephemeral:
            docker_client = EphemeralDockerRunnerClient(
                image=self.image,
                default_timeout_sec=int(self.timeout),
                memory_limit=self.memory_limit,
                cpu_limit=self.cpu_limit,
                command=self.command,
            )
            response = await docker_client.execute_turn(turn_request)
        else:
            client = WarmHttpRunnerClient(
                endpoint=self.endpoint,
                auth_token=os.getenv("RUNNER_AUTH_TOKEN"),
                default_timeout_sec=int(self.timeout),
            )
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
