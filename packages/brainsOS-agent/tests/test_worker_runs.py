"""Tests for the worker's email -> run -> reply orchestration (Ticket #295)."""

from __future__ import annotations

from email.message import EmailMessage
from pathlib import Path
from typing import Any

import pytest
import yaml
from brainsos_agent import worker as worker_mod
from brainsos_agent.adapters.hermes import HermesMailAdapter
from brainsos_agent.mail_runs import canonical_session_id, failure_email_body, idempotency_key_for
from brainsos_agent.models import OutboundEmail
from brainsos_queue.models import TaskStatus


def _raw_email(mid: str = "<msg-1@example.com>") -> bytes:
    em = EmailMessage()
    em["From"] = "operator@brainsos.local"
    em["To"] = "bawtford@brainsos.local"
    em["Subject"] = "Build me a page"
    em["Message-ID"] = mid
    em.set_content("Please build a landing page.")
    return em.as_bytes()


@pytest.fixture
def daemon(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "")  # disable trace posting
    manifest = tmp_path / "agents.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "agents": [
                    {
                        "id": "bawtford",
                        "name": "Bawtford",
                        "email": "bawtford@brainsos.local",
                        "runtime": "hermes",
                        "model": "qwen3.8:latest",
                        "memory_root": str(tmp_path / "mem" / "bawtford"),
                        "workspace_root": str(tmp_path / "ws" / "bawtford"),
                    }
                ]
            }
        )
    )
    d = worker_mod.AgentQueueWorkerDaemon(
        manifest_path=manifest, queue_db_path=tmp_path / "q" / "tasks.db", spool_dir=tmp_path / "spool"
    )
    sent: list[OutboundEmail] = []
    monkeypatch.setattr(d, "_send_reply", lambda profile, inbound, outbound: sent.append(outbound))
    d.sent = sent  # type: ignore[attr-defined]
    return d


class _FakeHermes(HermesMailAdapter):
    def __init__(self, behaviour: Any) -> None:
        super().__init__(runner_url="http://hermes/v1")
        self.behaviour = behaviour
        self.calls: list[Any] = []

    async def process_message(self, email, profile, resolved_soul=None, run_context=None):  # type: ignore[override]
        self.calls.append(run_context)
        return await self.behaviour(email, profile, run_context)


async def _enqueue_and_acquire(d, mid: str = "<msg-1@example.com>"):
    spool = d.spool_dir / "1.eml"
    raw = _raw_email(mid)
    spool.write_bytes(raw)
    await d.queue.enqueue(
        {"spool_path": str(spool), "raw_mime": raw.decode(), "recipient": "bawtford@brainsos.local", "message_id": mid}
    )
    task = await d.queue.acquire_task(worker_id="t")
    return task, spool


@pytest.mark.asyncio
async def test_success_checkpoints_run_id_sends_one_reply_and_marks_done(daemon, monkeypatch) -> None:
    async def ok(email, profile, ctx):
        await ctx.on_run_submitted("run_1", 123.0)
        return OutboundEmail(to=email.sender, subject="Re: x", body="Here it is", thread_id=email.thread_id,
                             metadata={"run_status": "completed", "run_id": "run_1"})

    fake = _FakeHermes(ok)
    monkeypatch.setattr(worker_mod, "get_runtime_adapter", lambda runtime: fake)
    task, spool = await _enqueue_and_acquire(daemon)

    await daemon.handle_task(task)

    assert [o.body for o in daemon.sent] == ["Here it is"]
    stored = await daemon.queue.get_task(task.id)
    assert stored.payload["hermes_run_id"] == "run_1"
    assert stored.payload["pending_reply"]["body"] == "Here it is"
    assert spool.with_suffix(".done").exists()


@pytest.mark.asyncio
async def test_retry_resumes_existing_run_instead_of_resubmitting(daemon, monkeypatch) -> None:
    async def resumed(email, profile, ctx):
        assert ctx.run_id == "run_1" and ctx.submitted_at == 123.0
        return OutboundEmail(to=email.sender, subject="Re: x", body="Resumed", thread_id=email.thread_id)

    fake = _FakeHermes(resumed)
    monkeypatch.setattr(worker_mod, "get_runtime_adapter", lambda runtime: fake)
    task, _ = await _enqueue_and_acquire(daemon)
    task.payload.update({"hermes_run_id": "run_1", "hermes_run_submitted_at": 123.0})

    await daemon.handle_task(task)
    assert [o.body for o in daemon.sent] == ["Resumed"]


@pytest.mark.asyncio
async def test_pending_reply_is_resent_without_rerunning_agent(daemon, monkeypatch) -> None:
    fake = _FakeHermes(None)
    monkeypatch.setattr(worker_mod, "get_runtime_adapter", lambda runtime: fake)
    task, _ = await _enqueue_and_acquire(daemon)
    task.payload["pending_reply"] = OutboundEmail(
        to="operator@brainsos.local", subject="Re: x", body="Already produced", thread_id="t"
    ).model_dump(mode="json")

    await daemon.handle_task(task)
    assert fake.calls == []
    assert [o.body for o in daemon.sent] == ["Already produced"]


@pytest.mark.asyncio
async def test_infra_error_retries_then_sends_failure_email_on_final_attempt(daemon, monkeypatch) -> None:
    async def boom(email, profile, ctx):
        raise RuntimeError("connection refused to hermes:8642")

    monkeypatch.setattr(worker_mod, "get_runtime_adapter", lambda runtime: _FakeHermes(boom))
    task, spool = await _enqueue_and_acquire(daemon)

    with pytest.raises(RuntimeError):  # attempt 1 of 3: no email, queue retries
        await daemon.handle_task(task)
    assert daemon.sent == [] and not spool.with_suffix(".done").exists()

    task.retries = task.max_retries - 1  # final attempt
    with pytest.raises(RuntimeError):
        await daemon.handle_task(task)
    assert len(daemon.sent) == 1
    assert "What you can do" in daemon.sent[0].body
    assert "connection refused" not in daemon.sent[0].body
    assert spool.with_suffix(".done").exists()  # dead-lettered emails are never replayed


@pytest.mark.asyncio
async def test_restart_does_not_reenqueue_known_spool_files(daemon) -> None:
    task, spool = await _enqueue_and_acquire(daemon)
    task.mark_failed("x")
    task.retries = task.max_retries
    task.status = TaskStatus.DEAD_LETTER
    await daemon.queue.update_task(task)

    fresh = worker_mod.AgentQueueWorkerDaemon(
        manifest_path=daemon.manifest_path, queue_db_path=daemon.queue_db_path, spool_dir=daemon.spool_dir
    )
    await fresh._load_known_tasks()
    assert spool.name in fresh._processed_spool_files
    assert "<msg-1@example.com>" in fresh._processed_message_ids


def test_canonical_session_id_is_stable_safe_and_agent_scoped() -> None:
    a = canonical_session_id("bawtford", "<1-6ac9@mail.local>")
    assert a == canonical_session_id("bawtford", "<1-6ac9@mail.local>")
    assert a != canonical_session_id("marvin", "<1-6ac9@mail.local>")
    assert set(a) <= set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
    long = canonical_session_id("bawtford", "<" + "x" * 500 + "@y>")
    assert len(long) <= 160


def test_idempotency_key_is_visible_ascii_and_bounded() -> None:
    key = idempotency_key_for("<abc def@x>", fallback="f")
    assert key == "mail:abcdef@x"
    assert len(idempotency_key_for("<" + "z" * 400 + ">", fallback="f")) <= 255


def test_failure_email_never_contains_raw_error_text() -> None:
    body = failure_email_body("timeout", agent_name="Bawtford", reference="run_1", budget_sec=7200)
    assert "2 hours" in body and "run_1" in body and body.endswith("— Bawtford")
