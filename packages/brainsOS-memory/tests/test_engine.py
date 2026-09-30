"""Tests for OKFEngine CRUD, keyword search, and prompt synthesis."""

import os
import tempfile
import unittest

from brainsos_memory.okf.engine import OKFEngine


class TestOKFEngine(unittest.TestCase):
    def test_write_and_read_note(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            engine = OKFEngine(root_dir=tmp_dir)

            note = engine.write_note(
                rel_path="knowledge/architecture.md",
                content="brainsOS runs on NVIDIA GB10 hardware.",
                title="Architecture",
                tags=["hw", "gb10"],
                priority="high",
            )
            self.assertEqual(note.title, "Architecture")
            self.assertTrue(os.path.exists(os.path.join(tmp_dir, "knowledge", "architecture.md")))

            loaded = engine.read_note("knowledge/architecture.md")
            self.assertEqual(loaded.title, "Architecture")
            self.assertIn("NVIDIA GB10", loaded.body)
            self.assertEqual(loaded.tags, ["hw", "gb10"])

    def test_write_rejects_non_markdown(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            engine = OKFEngine(root_dir=tmp_dir)
            with self.assertRaises(ValueError):
                engine.write_note(
                    rel_path="knowledge/data.sqlite",
                    content="bad data",
                )

    def test_write_rejects_binary(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            engine = OKFEngine(root_dir=tmp_dir)
            with self.assertRaises(ValueError):
                engine.write_note(
                    rel_path="knowledge/blob.md",
                    content="bad \x00 binary",
                )

    def test_list_and_search_notes(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            engine = OKFEngine(root_dir=tmp_dir)

            engine.write_note(
                rel_path="knowledge/sports.md",
                content="Football analytics and tactical formations.",
                title="Football Guide",
                tags=["sports", "football"],
            )
            engine.write_note(
                rel_path="knowledge/pets.md",
                content="Canine nutrition and daily wellness tracking.",
                title="Pet Care",
                tags=["animals", "wellness"],
            )

            notes = engine.list_notes()
            self.assertEqual(len(notes), 2)

            # Search keyword
            football_matches = engine.search("tactical")
            self.assertEqual(len(football_matches), 1)
            self.assertEqual(football_matches[0]["title"], "Football Guide")

            tag_matches = engine.search("wellness")
            self.assertEqual(len(tag_matches), 1)
            self.assertEqual(tag_matches[0]["title"], "Pet Care")

    def test_active_rules_synthesis(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            engine = OKFEngine(root_dir=tmp_dir)

            engine.write_note(
                rel_path="rules/rule1.md",
                content="Never execute unprivileged containers with root.",
                title="Rule 1: Unprivileged",
                priority="high",
                active=True,
            )
            engine.write_note(
                rel_path="rules/rule2.md",
                content="Inactive rule that should not show.",
                title="Rule 2: Inactive",
                priority="low",
                active=False,
            )

            context = engine.get_active_rules_context()
            self.assertIn("OPERATOR RULES & GUARDRAILS", context)
            self.assertIn("Rule 1: Unprivileged", context)
            self.assertNotIn("Rule 2: Inactive", context)

    def test_get_memory_dir_resolution(self):
        from brainsos_memory.okf.engine import get_memory_dir

        old_mem = os.environ.get("MEMORY_DIR")
        old_b_mem = os.environ.get("BRAINSOS_MEMORIES_DIR")
        old_data = os.environ.get("BRAINSOS_DATA_DIR")

        try:
            for k in ["MEMORY_DIR", "BRAINSOS_MEMORIES_DIR", "BRAINSOS_AGENT_MEMORIES_DIR", "BRAINSOS_DATA_DIR"]:
                os.environ.pop(k, None)
            self.assertEqual(get_memory_dir(), "/memories")

            os.environ["BRAINSOS_DATA_DIR"] = "/tmp/ext_data"
            self.assertEqual(get_memory_dir(), "/tmp/ext_data/agent_memories")

            os.environ["BRAINSOS_MEMORIES_DIR"] = "/tmp/custom_memories"
            self.assertEqual(get_memory_dir(), "/tmp/custom_memories")

            os.environ["MEMORY_DIR"] = "/container_memories"
            self.assertEqual(get_memory_dir(), "/container_memories")
        finally:
            for k, v in [
                ("MEMORY_DIR", old_mem),
                ("BRAINSOS_MEMORIES_DIR", old_b_mem),
                ("BRAINSOS_DATA_DIR", old_data),
            ]:
                if v is not None:
                    os.environ[k] = v
                else:
                    os.environ.pop(k, None)


if __name__ == "__main__":
    unittest.main()
