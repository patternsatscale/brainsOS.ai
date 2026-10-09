"""Unit tests for HermesMailAdapter's asynchronous /v1/runs pipeline (Ticket #295)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

import httpx
from brainsos_agent.adapters.hermes import (
    HermesMailAdapter,
    HermesUnavailableError,
    RunContext,
    WorkspaceBoundaryViolation,
)
from brainsos_agent.context import ContextAssembler
from brainsos_agent.models import AgentProfile
from brainsos_mail.models import ParsedInboundEmail


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


class FakeHermes:
    """Scriptable stand-in for the Hermes /v1/runs API."""

    def __init__(self, statuses: list[dict[str, Any]] | None = None, submit_codes: list[int] | None = None):
        self.statuses = list(statuses or [{"status": "completed", "output": "Done."}])
        self.submit_codes = list(submit_codes or [202])
        self.submits: list[dict[str, Any]] = []
        self.submit_headers: list[httpx.Headers] = []
        self.polls = 0
        self.stops = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and path.endswith("/v1/runs"):
            self.submits.append(json.loads(request.read()))
            self.submit_headers.append(request.headers)
            code = self.submit_codes.pop(0) if self.submit_codes else 202
            if code == 202:
                return httpx.Response(202, json={"run_id": "run_abc", "status": "started"})
            return httpx.Response(code, json={"error": {"message": f"code {code}"}})
        if request.method == "POST" and path.endswith("/stop"):
            self.stops += 1
            self.statuses = [{"status": "cancelled"}]
            return httpx.Response(200, json={"run_id": "run_abc", "status": "stopping"})
        if request.method == "GET" and "/v1/runs/" in path:
            self.polls += 1
            status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
            return httpx.Response(200, json={"run_id": "run_abc", **status})
        return httpx.Response(404)


class TestHermesRunsAdapter(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        root = Path(self.tmpdir.name)
        self.profiles: dict[str, AgentProfile] = {}
        for agent_id, name, soul, model in (
            ("bawtford", "Bawtford", "I am Bawtford, Creative Director.", "cindy-active-coding-model"),
            ("marvin", "Marvin", "I am Marvin, Sports Analytics Specialist.", "llama3.2:3b"),
        ):
            mem = root / "data" / "agent_memories" / agent_id
            ws = root / "data" / "agent_workspaces" / agent_id
            soul_path = root / "config" / "hermes" / agent_id / "SOUL.md"
            mem.mkdir(parents=True)
            ws.mkdir(parents=True)
            soul_path.parent.mkdir(parents=True)
            soul_path.write_text(soul, encoding="utf-8")
            self.profiles[agent_id] = AgentProfile(
                name=name,
                id=agent_id,
                email=f"{agent_id}@brainsos.local",
                runtime="hermes",
                model=model,
                soul_path=soul_path,
                memory_root=mem,
                workspace_root=ws,
                mcp_modules=["filesystem"],
            )
        self.clock = FakeClock()

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _email(self, agent_id: str = "bawtford", body: str = "Review spring launch.", mid: str = "<m-001@x>"):
        return ParsedInboundEmail(
            message_id=mid,
            thread_id="<thread-001@x>",
            sender="operator@brainsos.local",
            recipient=f"{agent_id}@brainsos.local",
            subject="Fashion Review",
            clean_body=body,
            raw_mime=b"",
        )

    def _adapter(self, hermes: FakeHermes, **kwargs: Any) -> HermesMailAdapter:
        client = httpx.AsyncClient(transport=httpx.MockTransport(hermes))
        return HermesMailAdapter(
            runner_url="http://hermes:8642/v1",
            http_client=client,
            poll_interval=5,
            max_run_sec=kwargs.pop("max_run_sec", 3600),
            submit_backoff=15,
            sleep=self.clock.sleep,
            clock=self.clock,
            **kwargs,
        )

    def _turns(self, agent_id: str = "bawtford") -> list[dict[str, str]]:
        return ContextAssembler.load_thread_turns(self.profiles[agent_id].memory_root, "<thread-001@x>")

    async def test_completed_run_returns_single_result_and_records_okf(self) -> None:
        hermes = FakeHermes(
            statuses=[
                {"status": "queued"},
                {"status": "running"},
                {"status": "completed", "output": "Spring launch looks great.", "usage": {"total_tokens": 42}},
            ]
        )
        checkpoints: list[tuple[str, float]] = []

        async def on_submit(run_id: str, submitted_at: float) -> None:
            checkpoints.append((run_id, submitted_at))

        out = await self._adapter(hermes).process_message(
            self._email(), self.profiles["bawtford"], run_context=RunContext(on_run_submitted=on_submit)
        )

        self.assertIn("Spring launch looks great.", out.body)
        self.assertIn("operator@brainsos.local wrote:", out.body)
        self.assertIsNotNone(out.html_body)
        self.assertIn("Spring launch looks great.", out.html_body)
        self.assertEqual(out.metadata["run_status"], "completed")
        self.assertEqual(out.metadata["run_id"], "run_abc")
        self.assertEqual(out.metadata["session_id"], "mail-bawtford-thread-001_x")
        self.assertEqual(len(hermes.submits), 1)
        self.assertEqual(hermes.polls, 3)
        self.assertEqual(checkpoints, [("run_abc", 1_000_000.0)])

        body = hermes.submits[0]
        self.assertEqual(body["input"], "Review spring launch.")
        self.assertEqual(body["model"], "cindy-active-coding-model")
        self.assertEqual(body["session_id"], "mail-bawtford-thread-001_x")
        self.assertIn("Creative Director", body["instructions"])
        self.assertEqual(body["conversation_history"], [])
        self.assertEqual(hermes.submit_headers[0]["Idempotency-Key"], "mail:m-001@x")

        turns = self._turns()
        self.assertEqual([t["role"] for t in turns], ["user", "assistant"])
        self.assertEqual(turns[1]["content"], "Spring launch looks great.")

    async def test_history_comes_from_okf_and_excludes_error_turns(self) -> None:
        mem = self.profiles["bawtford"].memory_root
        for role, text in (
            ("user", "First question"),
            ("assistant", "API call failed after 3 retries: HTTP 429: litellm.RateLimitError: slots in use"),
            ("user", "Second question"),
            ("assistant", "A real answer"),
        ):
            ContextAssembler.record_turn(mem, "<thread-001@x>", "Fashion Review", role, "x", text)
        hermes = FakeHermes()
        await self._adapter(hermes).process_message(self._email(), self.profiles["bawtford"])
        self.assertEqual(
            hermes.submits[0]["conversation_history"],
            [
                {"role": "user", "content": "First question"},
                {"role": "user", "content": "Second question"},
                {"role": "assistant", "content": "A real answer"},
            ],
        )

    async def test_failed_run_sends_failure_email_without_raw_error(self) -> None:
        hermes = FakeHermes(
            statuses=[{"status": "failed", "error": "HTTP 429: litellm.RateLimitError: max_parallel_requests=1"}]
        )
        out = await self._adapter(hermes).process_message(self._email(), self.profiles["bawtford"])
        self.assertEqual(out.metadata["run_status"], "failed")
        self.assertIn("What you can do", out.body)
        self.assertIn("run_abc", out.body)
        self.assertNotIn("litellm", out.body)
        self.assertNotIn("429", out.body)
        self.assertIn("RateLimitError", out.metadata["run_error"])
        self.assertEqual([t["role"] for t in self._turns()], ["user"])

    async def test_completed_with_empty_output_is_a_failure(self) -> None:
        hermes = FakeHermes(statuses=[{"status": "completed", "output": "   "}])
        out = await self._adapter(hermes).process_message(self._email(), self.profiles["bawtford"])
        self.assertEqual(out.metadata["run_status"], "empty")
        self.assertEqual([t["role"] for t in self._turns()], ["user"])

    async def test_interrupted_run_sends_failure_email(self) -> None:
        hermes = FakeHermes(statuses=[{"status": "interrupted", "error": "gateway restarted"}])
        out = await self._adapter(hermes).process_message(self._email(), self.profiles["bawtford"])
        self.assertEqual(out.metadata["run_status"], "interrupted")
        self.assertIn("restarted", out.body)

    async def test_budget_exceeded_stops_run_and_reports_timeout(self) -> None:
        hermes = FakeHermes(statuses=[{"status": "running"}])
        out = await self._adapter(hermes, max_run_sec=60).process_message(self._email(), self.profiles["bawtford"])
        self.assertEqual(hermes.stops, 1)
        self.assertEqual(out.metadata["run_status"], "timeout")
        self.assertIn("1 minute", out.body)
        self.assertEqual([t["role"] for t in self._turns()], ["user"])

    async def test_long_run_beyond_old_180s_timeout_completes(self) -> None:
        # 2 hours of "running" polls at 5s intervals, then completion: no timeout, one submit.
        hermes = FakeHermes(statuses=[{"status": "running"}] * 1440 + [{"status": "completed", "output": "Site built."}])
        out = await self._adapter(hermes, max_run_sec=14400).process_message(self._email(), self.profiles["bawtford"])
        self.assertIn("Site built.", out.body)
        self.assertIn("operator@brainsos.local wrote:", out.body)
        self.assertEqual(len(hermes.submits), 1)
        self.assertEqual(hermes.stops, 0)

    async def test_submit_429_backs_off_and_resubmits(self) -> None:
        hermes = FakeHermes(submit_codes=[429, 429, 202])
        out = await self._adapter(hermes).process_message(self._email(), self.profiles["bawtford"])
        self.assertEqual(out.metadata["run_status"], "completed")
        self.assertEqual(len(hermes.submits), 3)
        self.assertEqual(hermes.submits[0], hermes.submits[2])  # identical body -> idempotent replay

    async def test_submit_rejected_400_sends_failure_email(self) -> None:
        hermes = FakeHermes(submit_codes=[400])
        out = await self._adapter(hermes).process_message(self._email(), self.profiles["bawtford"])
        self.assertEqual(out.metadata["run_status"], "rejected")
        self.assertEqual(hermes.polls, 0)
        self.assertIn("configuration problem", out.body)

    async def test_submit_5xx_raises_for_queue_retry(self) -> None:
        hermes = FakeHermes(submit_codes=[503])
        with self.assertRaises(HermesUnavailableError):
            await self._adapter(hermes).process_message(self._email(), self.profiles["bawtford"])
        self.assertEqual(self._turns(), [])  # nothing recorded on a retryable failure

    async def test_resume_existing_run_does_not_resubmit(self) -> None:
        hermes = FakeHermes(statuses=[{"status": "running"}, {"status": "completed", "output": "Resumed result"}])
        ctx = RunContext(run_id="run_abc", submitted_at=self.clock.now - 100)
        out = await self._adapter(hermes).process_message(self._email(), self.profiles["bawtford"], run_context=ctx)
        self.assertEqual(hermes.submits, [])
        self.assertIn("Resumed result", out.body)
        self.assertIn("operator@brainsos.local wrote:", out.body)

    async def test_poll_404_is_interrupted(self) -> None:
        def transport(request: httpx.Request) -> httpx.Response:
            if request.method == "POST":
                return httpx.Response(202, json={"run_id": "run_gone"})
            return httpx.Response(404, json={"error": "not found"})

        adapter = HermesMailAdapter(
            runner_url="http://hermes:8642/v1",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)),
            sleep=self.clock.sleep,
            clock=self.clock,
        )
        out = await adapter.process_message(self._email(), self.profiles["bawtford"])
        self.assertEqual(out.metadata["run_status"], "interrupted")

    async def test_consecutive_multi_agent_invocation_no_state_bleeding(self) -> None:
        hermes = FakeHermes(statuses=[{"status": "completed", "output": "ok"}])
        adapter = self._adapter(hermes)
        await adapter.process_message(self._email("bawtford"), self.profiles["bawtford"])
        await adapter.process_message(self._email("marvin", mid="<m-002@x>"), self.profiles["marvin"])
        b, m = hermes.submits
        self.assertIn("Creative Director", b["instructions"])
        self.assertNotIn("Sports Analytics", b["instructions"])
        self.assertIn("Sports Analytics", m["instructions"])
        self.assertNotIn("Creative Director", m["instructions"])
        self.assertEqual(m["model"], "llama3.2:3b")
        self.assertNotEqual(b["session_id"], m["session_id"])
        self.assertEqual(m["conversation_history"], [])  # Marvin never sees Bawtford's thread turns

    async def test_resolved_soul_override(self) -> None:
        hermes = FakeHermes()
        await self._adapter(hermes).process_message(
            self._email(), self.profiles["bawtford"], resolved_soul="Overridden dynamic soul text"
        )
        self.assertIn("Overridden dynamic soul text", hermes.submits[0]["instructions"])

    def test_workspace_isolation_boundaries(self) -> None:
        adapter = HermesMailAdapter()
        profile = self.profiles["bawtford"]
        self.assertEqual(
            adapter.validate_workspace_path("notes.txt", profile), (profile.workspace_root / "notes.txt").resolve()
        )
        with self.assertRaises(WorkspaceBoundaryViolation):
            adapter.validate_workspace_path("../marvin/secret.txt", profile)
        with self.assertRaises(WorkspaceBoundaryViolation):
            adapter.validate_workspace_path("/etc/passwd", profile)


if __name__ == "__main__":
    unittest.main()
