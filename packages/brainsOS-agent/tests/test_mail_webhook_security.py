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


@pytest.mark.parametrize(
    "wildcard_host",
    [
        "0.0.0.0",
        "0.0",
        "0.0.0",
        "000.000.000.000",
        "0.0.0.000",
        "00",
        "0x0",
        "0x00000000",
        "0X00000000",
        "0x00.0x00.0x00.0x00",
        "[0.0]",
        "[0x00000000]",
        "::",
        "::0",
        "0:0:0:0:0:0:0:0",
        "0000:0000:0000:0000:0000:0000:0000:0000",
        "[::]",
        "[::0]",
        "::ffff:0.0.0.0",
        "::ffff:0:0",
        "[::ffff:0:0]",
        "::0%eth0",
        " 0:0:0:0:0:0:0:0 ",
        "*",
        "0",
        "   ",
    ],
)
def test_worker_refuses_wildcard_ingress_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, wildcard_host: str
) -> None:
    from brainsos_agent.worker import _is_unspecified_host, get_default_ingress_host

    monkeypatch.setenv("BRAINSOS_INGRESS_HOST", wildcard_host)
    resolved = get_default_ingress_host()
    assert not _is_unspecified_host(resolved)
    assert resolved != wildcard_host.strip()

    manifest = tmp_path / "agents.yaml"
    manifest.write_text("agents: []\n", encoding="utf-8")
    daemon = AgentQueueWorkerDaemon(
        manifest_path=manifest,
        queue_db_path=tmp_path / "tasks.db",
        spool_dir=tmp_path / "spool",
        ingress_host=wildcard_host,
    )
    assert not _is_unspecified_host(daemon.ingress_host)
    assert daemon.ingress_host != wildcard_host.strip()


@pytest.mark.parametrize("nul_host", ["0\x00", "0\x00127.0.0.1"])
def test_worker_refuses_nul_byte_ingress_host(tmp_path: Path, nul_host: str) -> None:
    from brainsos_agent.worker import _is_unspecified_host

    assert _is_unspecified_host(nul_host)

    manifest = tmp_path / "agents.yaml"
    manifest.write_text("agents: []\n", encoding="utf-8")
    daemon = AgentQueueWorkerDaemon(
        manifest_path=manifest,
        queue_db_path=tmp_path / "tasks.db",
        spool_dir=tmp_path / "spool",
        ingress_host=nul_host,
    )
    assert not _is_unspecified_host(daemon.ingress_host)
    assert daemon.ingress_host != nul_host


@pytest.mark.parametrize(
    "valid_host",
    [
        "127.0.0.1",
        "172.28.5.1",
        "::1",
        "[::1]",
        "localhost",
        "brainsos-mail",
        "0177.0.0.1",
        "010.0.0.1",
        "münchen.example",
    ],
)
def test_worker_preserves_valid_ingress_hosts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, valid_host: str
) -> None:
    from brainsos_agent.worker import _is_unspecified_host, get_default_ingress_host

    assert not _is_unspecified_host(valid_host)
    monkeypatch.setenv("BRAINSOS_INGRESS_HOST", valid_host)
    assert get_default_ingress_host() == valid_host

    manifest = tmp_path / "agents.yaml"
    manifest.write_text("agents: []\n", encoding="utf-8")
    daemon = AgentQueueWorkerDaemon(
        manifest_path=manifest,
        queue_db_path=tmp_path / "tasks.db",
        spool_dir=tmp_path / "spool",
        ingress_host=valid_host,
    )
    assert daemon.ingress_host == valid_host


@pytest.mark.parametrize(
    "unicode_wildcard",
    [
        "０.０.０.０",
        "０.０",
        "０",
        "０ｘ０",
        "０．０．０．０",
        "0｡0｡0｡0",
        "⁰.⁰.⁰.⁰",
        "₀.₀.₀.₀",
        "𝟢.𝟢.𝟢.𝟢",
        "０:０:０:０:０:０:０:０",
        "[０.０]",
        "[０:０:０:０:０:０:０:０]",
        "［０.０］",
        "＊",
        "[*]",
        "::ffff:０.０.０.０",
        "invalid..ä",
        "\u200b.ä",
    ],
)
def test_worker_refuses_unicode_idna_wildcard_ingress_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unicode_wildcard: str
) -> None:
    from brainsos_agent.worker import _is_unspecified_host, get_default_ingress_host

    assert _is_unspecified_host(unicode_wildcard)
    monkeypatch.setenv("BRAINSOS_INGRESS_HOST", unicode_wildcard)
    resolved = get_default_ingress_host()
    assert not _is_unspecified_host(resolved)
    assert resolved != unicode_wildcard.strip()

    manifest = tmp_path / "agents.yaml"
    manifest.write_text("agents: []\n", encoding="utf-8")
    daemon = AgentQueueWorkerDaemon(
        manifest_path=manifest,
        queue_db_path=tmp_path / "tasks.db",
        spool_dir=tmp_path / "spool",
        ingress_host=unicode_wildcard,
    )
    assert not _is_unspecified_host(daemon.ingress_host)
    assert daemon.ingress_host != unicode_wildcard.strip()


@pytest.mark.parametrize(
    ("host", "expected_bind", "expected_loopback"),
    [
        ("127.0.0.1", "127.0.0.1", True),
        ("0177.0.0.1", "0177.0.0.1", True),
        ("::1", "::1", True),
        ("[::1]", "::1", True),
        ("localhost", "localhost", True),
        ("172.28.5.1", "172.28.5.1", False),
        ("brainsos-mail", "brainsos-mail", False),
        ("010.0.0.1", "010.0.0.1", False),
    ],
)
def test_worker_bind_and_loopback_normalization(
    host: str, expected_bind: str, expected_loopback: bool
) -> None:
    from brainsos_agent.worker import _is_loopback_host, _normalize_bind_host

    bind_host = _normalize_bind_host(host)
    assert bind_host == expected_bind
    assert _is_loopback_host(bind_host) is expected_loopback


@pytest.mark.asyncio
@pytest.mark.parametrize("loopback_host", ["127.0.0.1", "0177.0.0.1", "::1", "[::1]", "localhost"])
async def test_worker_daemon_run_loopback_and_bracketed_ipv6_no_duplicate_bind(
    tmp_path: Path, loopback_host: str
) -> None:
    import asyncio
    import socket

    from brainsos_agent.worker import _normalize_bind_host

    probe_host = _normalize_bind_host(loopback_host)
    if probe_host == "localhost":
        probe_host = "127.0.0.1"
    family = socket.AF_INET6 if ":" in probe_host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        sock.bind((probe_host, 0))
        port = sock.getsockname()[1]

    manifest = tmp_path / "agents.yaml"
    manifest.write_text("agents: []\n", encoding="utf-8")
    daemon = AgentQueueWorkerDaemon(
        manifest_path=manifest,
        queue_db_path=tmp_path / "tasks.db",
        spool_dir=tmp_path / "spool",
        ingress_host=loopback_host,
        ingress_port=port,
    )

    async def _wait_and_stop() -> int:
        while not (daemon._http_runner and daemon._http_runner.sites):
            await asyncio.sleep(0.02)
        site_count = len(daemon._http_runner.sites)
        daemon.stop()
        return site_count

    stopper = asyncio.create_task(_wait_and_stop())
    await asyncio.wait_for(daemon.run(), timeout=5.0)
    assert await stopper == 1


@pytest.mark.asyncio
async def test_worker_daemon_run_binds_secondary_loopback_for_bridge_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    import brainsos_agent.worker as worker_mod

    bound_hosts: list[str] = []

    class FakeTCPSite:
        def __init__(self, runner: Any, host: str, port: int) -> None:
            self.host = host
            self.port = port

        async def start(self) -> None:
            bound_hosts.append(self.host)

    monkeypatch.setattr(worker_mod.web, "TCPSite", FakeTCPSite)

    manifest = tmp_path / "agents.yaml"
    manifest.write_text("agents: []\n", encoding="utf-8")
    daemon = AgentQueueWorkerDaemon(
        manifest_path=manifest,
        queue_db_path=tmp_path / "tasks.db",
        spool_dir=tmp_path / "spool",
        ingress_host="172.28.5.1",
        ingress_port=8000,
    )

    async def _stop_after_bind() -> None:
        while len(bound_hosts) < 2:
            await asyncio.sleep(0.02)
        daemon.stop()

    stopper = asyncio.create_task(_stop_after_bind())
    await asyncio.wait_for(daemon.run(), timeout=5.0)
    await stopper
    assert bound_hosts == ["172.28.5.1", "127.0.0.1"]


