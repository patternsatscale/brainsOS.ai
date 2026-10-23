"""Unit tests for brainsos_agent.prompts: modular prompt injection, resolution, and envelope rendering."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from brainsos_agent.models import AgentProfile
from brainsos_agent.prompts import (
    assemble_system_prompt,
    get_prompts_dirs,
    render_inbound_envelope,
    resolve_channel_prompt,
    resolve_global_prompts,
)


class TestPromptResolution(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)

        # Structure settings/prompts
        self.settings_prompts = self.root / "data" / "settings" / "prompts"
        self.global_dir = self.settings_prompts / "global"
        self.channels_dir = self.settings_prompts / "channels"
        self.envelopes_dir = self.settings_prompts / "envelopes"

        self.global_dir.mkdir(parents=True)
        self.channels_dir.mkdir(parents=True)
        self.envelopes_dir.mkdir(parents=True)

        # Seed global prompt
        (self.global_dir / "00_manifesto.md").write_text(
            "---\ntitle: Manifesto\n---\n# Patterns at Scale Manifesto\nWe scale discipline.",
            encoding="utf-8",
        )
        (self.global_dir / "10_safety.md").write_text(
            "# Safety Guidelines\nOperate with zero-trust sandboxing.",
            encoding="utf-8",
        )

        # Seed channel prompt
        (self.channels_dir / "email.md").write_text(
            "# Channel Directives: Email\nSummarize final response as an HTML email.",
            encoding="utf-8",
        )

        # Seed envelope template
        (self.envelopes_dir / "email.md").write_text(
            "[EMAIL]\nFrom: {sender}\nTo: {recipient}\nSubject: {subject}\n\n{body}\n[/EMAIL]",
            encoding="utf-8",
        )

        # Profile for terrastella
        self.mem_dir = self.root / "data" / "agents" / "terrastella" / "memories"
        self.ws_dir = self.root / "data" / "agents" / "terrastella" / "workspace"
        self.soul_path = self.root / "data" / "agents" / "terrastella" / "SOUL.md"
        self.mem_dir.mkdir(parents=True)
        self.ws_dir.mkdir(parents=True)
        self.soul_path.write_text("I am Terrastella, Operations Lead.", encoding="utf-8")

        self.profile = AgentProfile(
            name="Terrastella",
            id="terrastella",
            email="terrastella@brainsos.local",
            runtime="hermes",
            model="brainsos-core",
            soul_path=self.soul_path,
            memory_root=self.mem_dir,
            workspace_root=self.ws_dir,
        )

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_resolve_global_prompts_sorted_order(self) -> None:
        prompts = resolve_global_prompts(base_dir=self.root)
        self.assertEqual(len(prompts), 2)
        # Strips frontmatter and loads in sorted order 00_ then 10_
        self.assertIn("# Patterns at Scale Manifesto", prompts[0])
        self.assertNotIn("title: Manifesto", prompts[0])
        self.assertIn("Safety Guidelines", prompts[1])

    def test_resolve_channel_prompt_live_setting(self) -> None:
        prompt = resolve_channel_prompt("email", agent_id="terrastella", base_dir=self.root)
        self.assertIn("Channel Directives: Email", prompt)
        self.assertIn("HTML email", prompt)

    def test_resolve_channel_prompt_agent_override(self) -> None:
        agent_prompts = self.root / "data" / "agents" / "terrastella" / "prompts" / "channels"
        agent_prompts.mkdir(parents=True)
        (agent_prompts / "email.md").write_text(
            "# Custom Terrastella Email Rules\nSpeak like a flight controller.",
            encoding="utf-8",
        )

        prompt = resolve_channel_prompt("email", agent_id="terrastella", base_dir=self.root)
        self.assertIn("Custom Terrastella Email Rules", prompt)
        self.assertIn("flight controller", prompt)

    def test_resolve_channel_prompt_unknown_channel_returns_empty(self) -> None:
        prompt = resolve_channel_prompt("unsupported_carrier", agent_id="terrastella", base_dir=self.root)
        self.assertEqual(prompt, "")

    def test_render_inbound_envelope_with_template(self) -> None:
        metadata = {
            "sender": "alice@brainsos.local",
            "recipient": "terrastella@brainsos.local",
            "subject": "System Status",
            "date_utc": "2026-10-14 12:00:00 UTC",
            "thread_id": "<thread-99@local>",
        }
        rendered = render_inbound_envelope("email", metadata, "Check node 4.", base_dir=self.root)
        self.assertEqual(
            rendered,
            "[EMAIL]\nFrom: alice@brainsos.local\nTo: terrastella@brainsos.local\nSubject: System Status\n\nCheck node 4.\n[/EMAIL]",
        )

    def test_render_inbound_envelope_fallback(self) -> None:
        metadata = {
            "sender": "bob@brainsos.local",
            "recipient": "terrastella@brainsos.local",
            "subject": "Quick Question",
            "date_utc": "2026-10-14 12:00:00 UTC",
            "thread_id": "<thread-100@local>",
        }
        # Empty root with no envelope template
        empty_root = self.root / "empty"
        empty_root.mkdir()
        rendered = render_inbound_envelope("email", metadata, "Are you online?", base_dir=empty_root)
        self.assertIn("--- INBOUND EMAIL MESSAGE ---", rendered)
        self.assertIn("From: bob@brainsos.local", rendered)
        self.assertIn("Subject: Quick Question", rendered)
        self.assertIn("Are you online?", rendered)

    def test_assemble_system_prompt_all_layers(self) -> None:
        # Add memory rule
        rules_dir = self.mem_dir / "rules"
        rules_dir.mkdir()
        (rules_dir / "ops.md").write_text("Always verify telemetry before shutdown.", encoding="utf-8")

        prompt = assemble_system_prompt(self.profile, channel="email", base_dir=self.root)

        # Layer 0: Global Manifesto
        self.assertIn("# Patterns at Scale Manifesto", prompt)
        # Layer 1: Persona
        self.assertIn("Terrastella, Operations Lead", prompt)
        # Layer 2: Memory rule
        self.assertIn("Always verify telemetry before shutdown", prompt)
        # Layer 3: Runtime guidelines
        self.assertIn("Memory Partition: /data/agents/terrastella/memories", prompt)
        # Layer 4: Channel Directives
        self.assertIn("Channel Directives: Email", prompt)


if __name__ == "__main__":
    unittest.main()
