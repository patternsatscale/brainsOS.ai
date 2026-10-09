"""Hermes Mail Adapter for brainsOS Shared Stateless Agent Runner.

Ticket #295: one inbound email triggers exactly one asynchronous Hermes run via
``POST /v1/runs``. The adapter polls ``GET /v1/runs/{run_id}`` until the run reaches a
terminal status (runs may take seconds or hours), then returns exactly one reply:

* ``completed`` -> the agent's final output; the user + assistant turns are recorded in OKF.
* anything else -> a plain-language failure email with recommendations; only the user turn is
  recorded in OKF (failed output is never written as an assistant turn).

No socket is held open for the duration of the run, so client timeouts can never orphan an
agent loop. A wall-clock budget (``HERMES_RUN_MAX_SEC``) stops runaway runs via
``POST /v1/runs/{run_id}/stop``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from brainsos_mail.models import ParsedInboundEmail

from brainsos_agent.context import ContextAssembler
from brainsos_agent.mail_runs import (
    RUN_COMPLETED,
    RUN_EMPTY,
    RUN_INTERRUPTED,
    RUN_REJECTED,
    RUN_TIMEOUT,
    canonical_session_id,
    compose_reply_body,
    failure_email_body,
    idempotency_key_for,
)
from brainsos_agent.models import AgentProfile, OutboundEmail
from brainsos_agent.runtime import AgentRuntime
from brainsos_agent.souls import resolve_soul

logger = logging.getLogger("brainsos_agent.hermes")

TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "interrupted"})

# Assistant turns matching these signatures are infrastructure errors that leaked into OKF
# history before #295; they are excluded from conversation_history so they cannot poison runs.
_ERROR_TURN_PATTERNS = re.compile(
    r"(API call failed after \d+ retries|litellm\.\w+Error|RateLimitError|"
    r"max_parallel_requests|^\s*HTTP [45]\d\d\b|Traceback \(most recent call last\))",
    re.IGNORECASE | re.MULTILINE,
)


class WorkspaceBoundaryViolation(ValueError):
    """Raised when a tool execution or path escapes the agent's isolated workspace partition."""

    pass


class HermesUnavailableError(RuntimeError):
    """Transient infrastructure error (Hermes unreachable / 5xx). The queue retries the task."""


@dataclass
class RunContext:
    """Durable run checkpoint shared between the worker (queue payload) and the adapter."""

    run_id: str | None = None
    submitted_at: float | None = None
    on_run_submitted: Callable[[str, float], Awaitable[None]] | None = field(default=None, repr=False)


@dataclass
class RunResult:
    status: str
    output: str = ""
    error: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    run_id: str | None = None


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


class HermesMailAdapter(AgentRuntime):
    """Asynchronous run-based adapter routing inbound email through the shared warm Hermes runner."""

    def __init__(
        self,
        runner_url: str | None = None,
        http_client: httpx.AsyncClient | None = None,
        *,
        poll_interval: float | None = None,
        max_run_sec: float | None = None,
        http_timeout: float | None = None,
        submit_backoff: float | None = None,
        sleep: Callable[[float], Awaitable[Any]] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.runner_url = (runner_url or os.getenv("HERMES_RUNNER_URL", "http://127.0.0.1:8642/v1")).rstrip("/")
        self.poll_interval = poll_interval if poll_interval is not None else _env_float("HERMES_RUN_POLL_SEC", 5.0)
        self.max_run_sec = max_run_sec if max_run_sec is not None else _env_float("HERMES_RUN_MAX_SEC", 14400.0)
        self.http_timeout = http_timeout if http_timeout is not None else _env_float("HERMES_HTTP_TIMEOUT_SEC", 30.0)
        self.submit_backoff = (
            submit_backoff if submit_backoff is not None else _env_float("HERMES_RUN_SUBMIT_BACKOFF_SEC", 15.0)
        )
        self._sleep = sleep or asyncio.sleep
        self._clock = clock or time.time
        self._client = http_client

    # ------------------------------------------------------------------ helpers

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

        # 4. Email communication & formatting guidelines (HTML vs Markdown)
        parts.append(
            "\n### Email Communication & Formatting Guidelines\n"
            "- You are communicating directly via email with the recipient.\n"
            "- Start your email IMMEDIATELY with the opening salutation (e.g. `<p><strong>Dear <Name>,</strong></p>` or `<p>Hello <Name>,</p>`).\n"
            "- NEVER include meta-commentary, preamble, status updates, or thoughts before the salutation (e.g. do NOT say 'I have everything I need', 'Here is the report', or 'Sure, here is your email:'). Output ONLY the exact email body starting with the greeting.\n"
            "- Always format your responses in clean, modern HTML rather than Markdown.\n"
            "- Use standard HTML tags for structure and styling: `<p>`, `<strong>`, `<em>`, `<ul>`, `<li>`, `<ol>`, `<code>`, `<pre>`, `<blockquote>`, `<h3>`, `<a>`, `<table>`, `<tr>`, `<td>`.\n"
            "- Do NOT wrap your output in markdown code blocks like ```html ... ```; output clean HTML directly as your message body.\n"
            "- Do NOT use Markdown formatting syntax like `**bold**`, `*italic*`, `# heading`, or `- bullet`.\n"
            "- Write clean, structured, and modern email responses.\n"
        )

        return "\n\n".join(parts)

    @staticmethod
    def _conversation_history(profile: AgentProfile, thread_id: str) -> list[dict[str, str]]:
        """OKF thread turns (single source of history), minus leaked infrastructure-error turns."""
        history: list[dict[str, str]] = []
        for turn in ContextAssembler.load_thread_turns(profile.memory_root, thread_id):
            role = turn.get("role")
            content = (turn.get("content") or "").strip()
            if role not in ("user", "assistant") or not content:
                continue
            if role == "assistant" and _ERROR_TURN_PATTERNS.search(content):
                continue
            history.append({"role": role, "content": content})
        return history

    def _headers(self, profile: AgentProfile, idempotency_key: str | None = None) -> dict[str, str]:
        api_key = os.getenv("API_SERVER_KEY") or os.getenv("HERMES_API_KEY") or os.getenv("LITELLM_MASTER_KEY", "")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "X-BrainsOS-Agent": profile.id or profile.name,
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    # ------------------------------------------------------------------ Hermes /v1/runs

    async def _submit_run(
        self, client: httpx.AsyncClient, body: dict[str, Any], headers: dict[str, str], deadline: float
    ) -> tuple[str | None, RunResult | None]:
        """POST /v1/runs. Returns (run_id, None) or (None, terminal RunResult) for rejections.

        429 (Hermes run slot busy) backs off and resubmits until the run budget is exhausted.
        Connection errors and 5xx raise HermesUnavailableError so the queue retries the task.
        """
        endpoint = f"{self.runner_url}/runs"
        while True:
            try:
                resp = await client.post(endpoint, json=body, headers=headers, timeout=self.http_timeout)
            except httpx.HTTPError as e:
                raise HermesUnavailableError(f"Hermes submit failed: {e}") from e

            if resp.status_code in (200, 201, 202):
                run_id = (resp.json() or {}).get("run_id")
                if not run_id:
                    raise HermesUnavailableError(f"Hermes accepted the run without a run_id: {resp.text[:200]}")
                return run_id, None
            if resp.status_code == 429:
                if self._clock() + self.submit_backoff > deadline:
                    return None, RunResult(status=RUN_TIMEOUT, error="Hermes run slot stayed busy past the budget")
                logger.info("Hermes run slot busy (429); retrying submit in %.0fs", self.submit_backoff)
                await self._sleep(self.submit_backoff)
                continue
            if resp.status_code >= 500:
                raise HermesUnavailableError(f"Hermes submit HTTP {resp.status_code}: {resp.text[:200]}")
            # 400/401/403/409 etc. are not retryable: configuration or idempotency conflicts.
            return None, RunResult(status=RUN_REJECTED, error=f"HTTP {resp.status_code}: {resp.text[:500]}")

    async def _stop_run(self, client: httpx.AsyncClient, run_id: str, headers: dict[str, str]) -> None:
        try:
            await client.post(f"{self.runner_url}/runs/{run_id}/stop", headers=headers, timeout=self.http_timeout)
        except httpx.HTTPError as e:
            logger.warning("Failed to stop Hermes run %s: %s", run_id, e)

    async def _poll_run(
        self, client: httpx.AsyncClient, run_id: str, headers: dict[str, str], deadline: float
    ) -> RunResult:
        """Polls GET /v1/runs/{id} until terminal. Enforces the wall-clock budget via /stop."""
        endpoint = f"{self.runner_url}/runs/{run_id}"
        stop_requested_at: float | None = None
        while True:
            try:
                resp = await client.get(endpoint, headers=headers, timeout=self.http_timeout)
                if resp.status_code == 404:
                    return RunResult(status=RUN_INTERRUPTED, error="Hermes no longer knows this run", run_id=run_id)
                if resp.status_code >= 500:
                    raise httpx.HTTPStatusError("server error", request=resp.request, response=resp)
                data = resp.json() if resp.status_code == 200 else {}
            except httpx.HTTPError as e:
                # Hermes restarting / briefly unreachable: keep polling until the budget runs out.
                logger.warning("Polling Hermes run %s failed (%s); will retry", run_id, e)
                data = {}

            status = str(data.get("status") or "")
            if status in TERMINAL_STATUSES:
                if stop_requested_at is not None and status == "cancelled":
                    return RunResult(status=RUN_TIMEOUT, error="Run exceeded HERMES_RUN_MAX_SEC", run_id=run_id)
                return RunResult(
                    status=status,
                    output=str(data.get("output") or "").strip(),
                    error=data.get("error"),
                    usage=data.get("usage") or {},
                    run_id=run_id,
                )

            now = self._clock()
            if now >= deadline:
                if stop_requested_at is None:
                    logger.warning("Hermes run %s exceeded budget (%.0fs); requesting stop", run_id, self.max_run_sec)
                    await self._stop_run(client, run_id, headers)
                    stop_requested_at = now
                elif now - stop_requested_at > max(60.0, 6 * self.poll_interval):
                    return RunResult(status=RUN_TIMEOUT, error="Run exceeded HERMES_RUN_MAX_SEC", run_id=run_id)
            await self._sleep(self.poll_interval)

    # ------------------------------------------------------------------ AgentRuntime SPI

    async def process_message(
        self,
        email: ParsedInboundEmail,
        profile: AgentProfile,
        resolved_soul: str | None = None,
        run_context: RunContext | None = None,
    ) -> OutboundEmail:
        """Runs one email through one Hermes run and returns exactly one reply (result or failure)."""
        ctx = run_context or RunContext()
        agent_id = profile.id or profile.name
        session_id = canonical_session_id(agent_id, email.thread_id)
        user_text = (email.clean_body or email.body or "").strip() or f"(No message body. Subject: {email.subject})"

        # The request body is deterministic for a given email + OKF state, so a resubmit after a
        # worker crash replays the original run via Idempotency-Key instead of starting a new one.
        body: dict[str, Any] = {
            "input": user_text,
            "instructions": self._assemble_system_prompt_with_working_memory(profile, resolved_soul=resolved_soul),
            "conversation_history": self._conversation_history(profile, email.thread_id),
            "session_id": session_id,
            "model": profile.model,
        }
        headers = self._headers(
            profile, idempotency_key_for(email.message_id, fallback=f"{agent_id}:{email.thread_id}:{user_text}")
        )

        client = self._client or httpx.AsyncClient()
        try:
            if ctx.run_id:
                logger.info("Resuming Hermes run %s for session %s", ctx.run_id, session_id)
                started_at = ctx.submitted_at or self._clock()
                result = await self._poll_run(client, ctx.run_id, headers, started_at + self.max_run_sec)
            else:
                started_at = self._clock()
                run_id, rejected = await self._submit_run(client, body, headers, started_at + self.max_run_sec)
                if rejected is not None:
                    result = rejected
                else:
                    assert run_id is not None
                    logger.info("Submitted Hermes run %s for session %s (%s)", run_id, session_id, agent_id)
                    ctx.run_id, ctx.submitted_at = run_id, started_at
                    if ctx.on_run_submitted:
                        await ctx.on_run_submitted(run_id, started_at)
                    result = await self._poll_run(client, run_id, headers, started_at + self.max_run_sec)
        finally:
            if self._client is None:
                await client.aclose()

        if result.status == RUN_COMPLETED and not result.output:
            result.status, result.error = RUN_EMPTY, result.error or "Run completed with empty output"

        # OKF is the single source of history: user turn always, assistant turn only on success.
        ContextAssembler.record_turn(
            memory_root=profile.memory_root,
            thread_id=email.thread_id,
            subject=email.subject,
            role="user",
            author=email.sender,
            content=user_text,
        )
        if result.status == RUN_COMPLETED:
            ContextAssembler.record_turn(
                memory_root=profile.memory_root,
                thread_id=email.thread_id,
                subject=email.subject,
                role="assistant",
                author=profile.email,
                content=result.output,
            )
            raw_reply = result.output
        else:
            logger.warning(
                "Hermes run %s for session %s ended with status=%s: %s",
                result.run_id,
                session_id,
                result.status,
                result.error,
            )
            raw_reply = failure_email_body(
                result.status,
                agent_name=profile.name,
                reference=result.run_id,
                budget_sec=self.max_run_sec,
            )

        plain_body, html_body = compose_reply_body(raw_reply, email)
        clean_subj = email.subject if email.subject.lower().startswith("re:") else f"Re: {email.subject}"
        return OutboundEmail(
            to=email.sender,
            subject=clean_subj,
            body=plain_body,
            html_body=html_body,
            thread_id=email.thread_id,
            in_reply_to=email.message_id,
            references=email.message_id,
            metadata={
                "model": profile.model,
                "agent_id": profile.id,
                "session_id": session_id,
                "run_id": result.run_id,
                "run_status": result.status,
                "run_error": result.error,
                "usage": result.usage,
                "input": user_text,
                "started_at": started_at,
                "ended_at": self._clock(),
            },
        )


__all__ = [
    "HermesMailAdapter",
    "HermesUnavailableError",
    "RunContext",
    "RunResult",
    "WorkspaceBoundaryViolation",
]
