"""Regression tests for Ticket #388: mail inbound webhook auth & spool traversal containment."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import make_mocked_request
from brainsos_agent.worker import AgentQueueWorkerDaemon


def _make_daemon(tmp_path: Path, webhook_secret: str | None = "secret-hook-388") -> AgentQueueWorkerDaemon:
    manifest = tmp_path / "agents.yaml"
    manifest.write_text(
        "agents:\n"
        "  ping:\n"
        "    name: Ping\n"
        "    email: ping@brainsos.local\n"
        "    adapter: deterministic\n",
        encoding="utf-8",
    )
    spool_dir = tmp_path / "spool"
    spool_dir.mkdir(parents=True, exist_ok=True)
    daemon = AgentQueueWorkerDaemon(
        manifest_path=manifest,
        queue_db_path=tmp_path / "tasks.db",
        spool_dir=spool_dir,
        mail_webhook_secret=webhook_secret,
    )
    object.__setattr__(
        daemon.queue,
        "enqueue",
        AsyncMock(side_effect=lambda payload, partition_key: type("T", (), {"id": "task-1"})()),
    )
    return daemon


def _mock_request(raw: bytes, headers: dict[str, str]) -> Any:
    req = make_mocked_request("POST", "/api/v1/mail/inbound", headers=headers)
    object.__setattr__(req, "read", AsyncMock(return_value=raw))
    return req


@pytest.mark.asyncio
async def test_mail_inbound_requires_webhook_secret(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MAIL_WEBHOOK_SECRET", raising=False)
    raw = (
        b"From: admin@brainsos.local\r\n"
        b"To: ping@brainsos.local\r\n"
        b"Subject: Test\r\n"
        b"Message-ID: <m1@brainsos.local>\r\n\r\nhello\r\n"
    )

    daemon_unconfigured = _make_daemon(tmp_path, webhook_secret="")
    resp_unconf = await daemon_unconfigured.handle_inbound_http(_mock_request(raw, {}))
    assert resp_unconf.status == 401

    daemon = _make_daemon(tmp_path, webhook_secret="secret-hook-388")
    resp_missing = await daemon.handle_inbound_http(_mock_request(raw, {}))
    assert resp_missing.status == 401

    resp_bad = await daemon.handle_inbound_http(
        _mock_request(raw, {"X-Mail-Webhook-Secret": "wrong"})
    )
    assert resp_bad.status == 401


@pytest.mark.asyncio
async def test_mail_inbound_enforces_spool_basename_containment(tmp_path: Path) -> None:
    daemon = _make_daemon(tmp_path, webhook_secret="secret-hook-388")
    outside_target = tmp_path / "escape.eml"
    outside_target.write_bytes(b"SENSITIVE_HOST_FILE")

    raw = (
        b"From: admin@brainsos.local\r\n"
        b"To: ping@brainsos.local\r\n"
        b"Subject: Spool Traversal Test\r\n"
        b"Message-ID: <m2@brainsos.local>\r\n\r\nping\r\n"
    )
    req = _mock_request(
        raw,
        {
            "X-Mail-Webhook-Secret": "secret-hook-388",
            "X-Spool-Filename": "../../escape.eml",
        },
    )
    resp = await daemon.handle_inbound_http(req)
    assert resp.status == 200
    assert daemon.queue.enqueue.await_count == 1  # type: ignore[attr-defined]
    enqueued_payload = daemon.queue.enqueue.call_args.kwargs["payload"]  # type: ignore[attr-defined]
    spool_path = Path(enqueued_payload["spool_path"]).resolve()
    assert spool_path.is_relative_to(daemon.spool_dir.resolve())
    assert spool_path != outside_target.resolve()
