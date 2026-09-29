"""Unit tests for HermesMailAdapter and stateless runner dynamic hydration."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import httpx
from brainsos_agent.adapters.hermes import HermesMailAdapter, WorkspaceBoundaryViolation
from brainsos_agent.models import AgentProfile
from brainsos_mail.models import ParsedInboundEmail


class TestHermesAdapter(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)

        # Scaffolding for Bawtford
        self.bawtford_mem = self.root / "data" / "agent_memories" / "bawtford"
        self.bawtford_ws = self.root / "data" / "agent_workspaces" / "bawtford"
        self.bawtford_soul = self.root / "config" / "hermes" / "bawtford" / "SOUL.md"
        self.bawtford_mem.mkdir(parents=True, exist_ok=True)
        self.bawtford_ws.mkdir(parents=True, exist_ok=True)
        self.bawtford_soul.parent.mkdir(parents=True, exist_ok=True)
        self.bawtford_soul.write_text("I am Bawtford, Creative Director.", encoding="utf-8")

        self.bawtford_profile = AgentProfile(
            name="Bawtford",
            id="bawtford",
            email="bawtford@brainsos.local",
            runtime="hermes",
            model="cindy-active-coding-model",
            soul_path=self.bawtford_soul,
            memory_root=self.bawtford_mem,
            workspace_root=self.bawtford_ws,
            mcp_modules=["filesystem"],
        )

        # Scaffolding for Marvin
        self.marvin_mem = self.root / "data" / "agent_memories" / "marvin"
        self.marvin_ws = self.root / "data" / "agent_workspaces" / "marvin"
        self.marvin_soul = self.root / "config" / "hermes" / "marvin" / "SOUL.md"
        self.marvin_mem.mkdir(parents=True, exist_ok=True)
        self.marvin_ws.mkdir(parents=True, exist_ok=True)
        self.marvin_soul.parent.mkdir(parents=True, exist_ok=True)
        self.marvin_soul.write_text("I am Marvin, Sports Analytics Specialist.", encoding="utf-8")

        self.marvin_profile = AgentProfile(
            name="Marvin",
            id="marvin",
            email="marvin@brainsos.local",
            runtime="hermes",
            model="llama3.2:3b",
            soul_path=self.marvin_soul,
            memory_root=self.marvin_mem,
            workspace_root=self.marvin_ws,
            mcp_modules=["filesystem"],
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    async def test_consecutive_multi_agent_invocation_no_state_bleeding(self):
        """Verify Bawtford and Marvin run through the same adapter instance without state leakage."""
        captured_requests: list[dict] = []

        def mock_transport(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.read())
            captured_requests.append(body)
            agent_id = request.headers.get("X-BrainsOS-Agent", "unknown")
            return httpx.Response(
                status_code=200,
                json={
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": f"Hello from {agent_id}",
                                "tool_calls": [],
                            }
                        }
                    ],
                    "usage": {"total_tokens": 120},
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(mock_transport))
        adapter = HermesMailAdapter(http_client=client)

        # 1. First invocation: Bawtford
        email_bawtford = ParsedInboundEmail(
            message_id="<bawt-001@brainsos.local>",
            thread_id="<bawt-001@brainsos.local>",
            sender="operator@brainsos.local",
            recipient="bawtford@brainsos.local",
            subject="Fashion Review",
            clean_body="Review spring season launch.",
            raw_mime=b"",
        )

        out_b = await adapter.process_message(email_bawtford, self.bawtford_profile)
        self.assertEqual(out_b.body, "Hello from bawtford")

        # 2. Second invocation: Marvin
        email_marvin = ParsedInboundEmail(
            message_id="<marv-001@brainsos.local>",
            thread_id="<marv-001@brainsos.local>",
            sender="operator@brainsos.local",
            recipient="marvin@brainsos.local",
            subject="Analytics Matchup",
            clean_body="Provide score projection for tonight.",
            raw_mime=b"",
        )

        out_m = await adapter.process_message(email_marvin, self.marvin_profile)
        self.assertEqual(out_m.body, "Hello from marvin")

        # Verify requests isolation
        self.assertEqual(len(captured_requests), 2)

        req1, req2 = captured_requests[0], captured_requests[1]

        # Bawtford's request must only contain Bawtford persona and workspace
        self.assertEqual(req1["model"], "cindy-active-coding-model")
        self.assertIn("Creative Director", req1["messages"][0]["content"])
        self.assertNotIn("Sports Analytics", req1["messages"][0]["content"])
        self.assertEqual(req1["extra_body"]["workspace_root"], str(self.bawtford_ws))

        # Marvin's request must only contain Marvin persona and workspace
        self.assertEqual(req2["model"], "llama3.2:3b")
        self.assertIn("Sports Analytics", req2["messages"][0]["content"])
        self.assertNotIn("Creative Director", req2["messages"][0]["content"])
        self.assertEqual(req2["extra_body"]["workspace_root"], str(self.marvin_ws))

    async def test_tool_calls_extraction(self):
        """Verify adapter extracts tool calls and metadata properly."""
        def mock_transport(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code=200,
                json={
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "I looked up the stats.",
                                "tool_calls": [
                                    {
                                        "id": "call_123",
                                        "type": "function",
                                        "function": {"name": "search_data", "arguments": '{"q": "stats"}'},
                                    }
                                ],
                            }
                        }
                    ],
                    "usage": {"total_tokens": 150},
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(mock_transport))
        adapter = HermesMailAdapter(http_client=client)

        email = ParsedInboundEmail(
            message_id="<marv-002@brainsos.local>",
            thread_id="<marv-002@brainsos.local>",
            sender="operator@brainsos.local",
            recipient="marvin@brainsos.local",
            subject="Stats",
            clean_body="Check stats",
            raw_mime=b"",
        )

        out = await adapter.process_message(email, self.marvin_profile)
        self.assertEqual(out.body, "I looked up the stats.")
        self.assertEqual(len(out.metadata["tool_calls"]), 1)
        self.assertEqual(out.metadata["tool_calls"][0]["function"]["name"], "search_data")

    def test_workspace_isolation_boundaries(self):
        """Verify workspace boundary checks prevent directory traversal."""
        adapter = HermesMailAdapter()

        # Valid subpath inside workspace root
        valid_path = adapter.validate_workspace_path("notes.txt", self.bawtford_profile)
        self.assertEqual(valid_path, (self.bawtford_ws / "notes.txt").resolve())

        # Attempt to escape workspace to Marvin's workspace
        with self.assertRaises(WorkspaceBoundaryViolation):
            adapter.validate_workspace_path("../marvin/secret.txt", self.bawtford_profile)

        # Attempt to access root filesystem
        with self.assertRaises(WorkspaceBoundaryViolation):
            adapter.validate_workspace_path("/etc/passwd", self.bawtford_profile)


if __name__ == "__main__":
    unittest.main()
