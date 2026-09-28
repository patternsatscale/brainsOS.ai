"""Tests for OKFNote models and YAML frontmatter serialization."""

import unittest

from brainsos_memory.okf.models import OKFNote


class TestOKFModels(unittest.TestCase):
    def test_okf_note_creation(self):
        note = OKFNote(
            rel_path="knowledge/test.md",
            title="Test Note",
            note_type="knowledge",
            tags=["ai", "brainsos"],
            body="This is a test note body.",
        )
        self.assertEqual(note.title, "Test Note")
        self.assertEqual(note.note_type, "knowledge")
        self.assertEqual(note.tags, ["ai", "brainsos"])
        self.assertTrue(note.active)
        self.assertEqual(note.priority, "normal")
        self.assertEqual(note.body, "This is a test note body.")

    def test_okf_note_serialization_and_parsing(self):
        original = OKFNote(
            rel_path="rules/sample_rule.md",
            title="Sample Rule",
            note_type="rules",
            tags=["critical", "hardware"],
            active=True,
            priority="high",
            body="Always enforce hardware serialization.",
        )
        serialized = original.serialize()
        self.assertIn("---", serialized)
        self.assertIn("title: Sample Rule", serialized)
        self.assertIn("priority: high", serialized)

        parsed = OKFNote.parse("rules/sample_rule.md", serialized)
        self.assertEqual(parsed.title, original.title)
        self.assertEqual(parsed.note_type, original.note_type)
        self.assertEqual(parsed.tags, original.tags)
        self.assertEqual(parsed.body, original.body)
        self.assertEqual(parsed.priority, "high")
        self.assertTrue(parsed.active)

    def test_okf_note_empty_frontmatter(self):
        content = "Raw note without frontmatter."
        parsed = OKFNote.parse("knowledge/raw.md", content)
        self.assertEqual(parsed.title, "raw")
        self.assertEqual(parsed.body, content)
        self.assertEqual(parsed.note_type, "knowledge")


if __name__ == "__main__":
    unittest.main()
