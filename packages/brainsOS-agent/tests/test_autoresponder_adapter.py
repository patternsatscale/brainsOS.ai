"""Unit tests for AutoResponderAdapter and multi-runtime adapter registry."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from brainsos_agent.adapters import AutoResponderAdapter, RunnerMailAdapter, get_runtime_adapter
from brainsos_agent.context import ContextAssembler
from brainsos_agent.models import AgentProfile
from brainsos_mail.models import ParsedInboundEmail


class TestAutoResponderAdapter(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)

        self.memory_root = self.root / "data" / "agent_memories" / "ping"
        self.workspace_root = self.root / "data" / "agent_workspaces" / "ping"
        self.soul_path = self.root / "config" / "hermes" / "ping" / "SOUL.md"

        self.memory_root.mkdir(parents=True, exist_ok=True)
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.soul_path.parent.mkdir(parents=True, exist_ok=True)
        self.soul_path.write_text("You are Ping, auto-responder agent.", encoding="utf-8")

        self.profile = AgentProfile(
            name="Ping - Auto-Responder & Verification Agent",
            id="ping",
            email="ping@brainsos.local",
            runtime="autoresponder",
            model="none/deterministic",
            soul_path=self.soul_path,
            memory_root=self.memory_root,
            workspace_root=self.workspace_root,
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    async def test_autoresponder_reply_generation(self):
        """Verify AutoResponderAdapter generates deterministic ack with threading headers."""
        adapter = AutoResponderAdapter(greeting_prefix="Ack:")

        inbound = ParsedInboundEmail(
            message_id="<client-ping-001@brainsos.local>",
            thread_id="<client-ping-001@brainsos.local>",
            sender="operator@brainsos.local",
            recipient="ping@brainsos.local",
            subject="Integration Connectivity Ping",
            clean_body="Testing auto-responder loop without LLM.",
            raw_mime=b"",
        )

        outbound = await adapter.process_message(inbound, self.profile)

        self.assertEqual(outbound.to, "operator@brainsos.local")
        self.assertEqual(outbound.subject, "Re: Integration Connectivity Ping")
        self.assertEqual(outbound.in_reply_to, "<client-ping-001@brainsos.local>")
        self.assertEqual(outbound.references, "<client-ping-001@brainsos.local>")
        self.assertIn("Ack:", outbound.body)
        self.assertIn("Integration Connectivity Ping", outbound.body)
        self.assertIn("Testing auto-responder loop without LLM.", outbound.body)
        self.assertEqual(outbound.metadata["adapter"], "autoresponder")

    async def test_autoresponder_persists_okf_memory(self):
        """Verify AutoResponderAdapter records inbound and reply turns into OKF thread file."""
        adapter = AutoResponderAdapter()

        thread_id = "<test-thread-okf-999@brainsos.local>"
        inbound = ParsedInboundEmail(
            message_id=thread_id,
            thread_id=thread_id,
            sender="operator@brainsos.local",
            recipient="ping@brainsos.local",
            subject="Memory Test",
            clean_body="Check memory turn recording.",
            raw_mime=b"",
        )

        await adapter.process_message(inbound, self.profile)

        # Verify thread dialogue file exists and has 2 turns
        turns = ContextAssembler.load_thread_turns(self.profile.memory_root, thread_id)
        self.assertEqual(len(turns), 2)
        self.assertEqual(turns[0]["role"], "user")
        self.assertEqual(turns[0]["content"], "Check memory turn recording.")
        self.assertEqual(turns[1]["role"], "assistant")
        self.assertIn("Auto-responder ACK", turns[1]["content"])

    def test_get_runtime_adapter_factory(self):
        """Verify runtime adapter factory resolves to expected adapter classes."""
        self.assertIsInstance(get_runtime_adapter("autoresponder"), AutoResponderAdapter)
        self.assertIsInstance(get_runtime_adapter("echo"), AutoResponderAdapter)
        self.assertIsInstance(get_runtime_adapter("ping"), AutoResponderAdapter)
        self.assertIsInstance(get_runtime_adapter("dummy"), AutoResponderAdapter)
        self.assertIsInstance(get_runtime_adapter("hermes"), RunnerMailAdapter)
        self.assertIsInstance(get_runtime_adapter(None), RunnerMailAdapter)

        with self.assertRaises(ValueError):
            get_runtime_adapter("unsupported_fake_runtime")


if __name__ == "__main__":
    unittest.main()
