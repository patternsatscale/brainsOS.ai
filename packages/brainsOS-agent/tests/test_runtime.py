"""Unit tests for brainsOS-agent runtime SPI, profile parsing, and context assembly."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from brainsos_agent.context import ContextAssembler, sanitize_thread_filename
from brainsos_agent.models import AgentProfile, OutboundEmail
from brainsos_agent.runtime import AgentRuntime
from brainsos_mail.models import ParsedInboundEmail


class MockEchoRuntime(AgentRuntime):
    """Test concrete implementation of AgentRuntime."""

    async def process_message(
        self,
        email: ParsedInboundEmail,
        profile: AgentProfile,
    ) -> OutboundEmail:
        _ = ContextAssembler.assemble_messages(email, profile, record_inbound=True)
        response_text = f"Acknowledged '{email.subject}': {email.clean_body}"

        ContextAssembler.record_turn(
            memory_root=profile.memory_root,
            thread_id=email.thread_id,
            subject=email.subject,
            role="assistant",
            author=profile.email,
            content=response_text,
        )

        return OutboundEmail(
            to=email.sender,
            subject=f"Re: {email.subject}",
            body=response_text,
            thread_id=email.thread_id,
            in_reply_to=email.message_id,
            references=email.message_id,
        )


class TestAgentRuntime(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.memory_root = self.root / "data" / "agent_memories" / "terrastella"
        self.workspace_root = self.root / "data" / "agent_workspaces" / "terrastella"
        self.soul_path = self.root / "config" / "hermes" / "terrastella" / "SOUL.md"

        self.memory_root.mkdir(parents=True, exist_ok=True)
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.soul_path.parent.mkdir(parents=True, exist_ok=True)
        self.soul_path.write_text("You are Terrastella, the primary operations agent.", encoding="utf-8")

        self.profile = AgentProfile(
            name="Terrastella",
            id="terrastella",
            email="terrastella@brainsos.local",
            runtime="hermes",
            model="brainsos-core",
            soul_path=self.soul_path,
            memory_root=self.memory_root,
            workspace_root=self.workspace_root,
            mcp_modules=["filesystem", "email"],
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_parse_live_manifest_yaml(self):
        """Validate AgentProfile against repo config/default_settings/agents.yaml."""
        manifest_path = (
            Path("data/settings/agents.yaml")
            if Path("data/settings/agents.yaml").exists()
            else Path("config/default_settings/agents.yaml")
        )
        self.assertTrue(manifest_path.exists(), f"Manifest must exist at {manifest_path}")

        profiles = AgentProfile.from_manifest_yaml(manifest_path)
        self.assertIsInstance(profiles, list)
        self.assertGreaterEqual(len(profiles), 3)

        agent_ids = [p.id for p in profiles]
        self.assertIn("terrastella", agent_ids)
        self.assertIn("marvin", agent_ids)
        self.assertIn("bawtford", agent_ids)

        terrastella = AgentProfile.from_manifest_yaml(manifest_path, agent_id="terrastella")
        self.assertEqual(terrastella.id, "terrastella")
        self.assertEqual(terrastella.email, "terrastella@brainsos.local")
        self.assertEqual(terrastella.runtime, "hermes")
        self.assertEqual(terrastella.model, "brainsos-core")

    def test_sanitize_thread_filename(self):
        self.assertEqual(sanitize_thread_filename("<msg-123@brainsos.local>"), "msg-123_brainsos.local.md")
        self.assertTrue(sanitize_thread_filename("clean-thread").endswith(".md"))

    async def test_context_assembly_and_okf_memory_reconstruction(self):
        """Verify context assembler creates human-auditable OKF Markdown without raw quotes."""
        email1 = ParsedInboundEmail(
            message_id="<msg-001@brainsos.local>",
            thread_id="<msg-001@brainsos.local>",
            sender="alice@brainsos.local",
            recipient="terrastella@brainsos.local",
            subject="Cluster Health",
            clean_body="Can you report cluster status?",
            raw_mime=b"",
        )

        runtime = MockEchoRuntime()
        out1 = await runtime.process_message(email1, self.profile)
        self.assertEqual(out1.to, "alice@brainsos.local")
        self.assertIn("Can you report cluster status?", out1.body)

        # Check OKF Markdown thread file created in memory
        thread_file = ContextAssembler.get_thread_file_path(self.memory_root, email1.thread_id)
        self.assertTrue(thread_file.exists())
        self.assertTrue(str(thread_file).endswith(".md"))

        content = thread_file.read_text(encoding="utf-8")
        self.assertIn('type: "thread-dialogue"', content)
        self.assertIn("## Turn 1: user", content)
        self.assertIn("## Turn 2: assistant", content)

        # Second turn in the same conversation
        email2 = ParsedInboundEmail(
            message_id="<msg-002@brainsos.local>",
            thread_id="<msg-001@brainsos.local>",
            sender="alice@brainsos.local",
            recipient="terrastella@brainsos.local",
            subject="Re: Cluster Health",
            clean_body="Great, and what about memory usage?",
            raw_mime=b"",
        )

        out2 = await runtime.process_message(email2, self.profile)
        self.assertEqual(out2.in_reply_to, "<msg-002@brainsos.local>")

        # Verify reconstructed messages fed into LLM context
        messages = ContextAssembler.assemble_messages(email2, self.profile, record_inbound=False)
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("Terrastella", messages[0]["content"])

        # History should contain turn 1 user, turn 1 assistant, and turn 2 user
        roles = [m["role"] for m in messages]
        self.assertEqual(roles, ["system", "user", "assistant", "user", "assistant", "user"])
        self.assertEqual(messages[-1]["content"], "Great, and what about memory usage?")

    def test_invalid_email_format_raises_validation_error(self):
        with self.assertRaises(Exception):
            AgentProfile(
                name="Invalid",
                email="not-an-email",
                soul_path=self.soul_path,
                memory_root=self.memory_root,
                workspace_root=self.workspace_root,
            )

    def test_manifest_nonexistent_agent_raises_error(self):
        manifest_path = Path("config/agents.yaml")
        with self.assertRaises(ValueError):
            AgentProfile.from_manifest_yaml(manifest_path, agent_id="nonexistent-ghost-agent")

    def test_empty_thread_history_returns_empty_list(self):
        turns = ContextAssembler.load_thread_turns(self.memory_root, "nonexistent-thread-id")
        self.assertEqual(turns, [])


if __name__ == "__main__":
    unittest.main()
