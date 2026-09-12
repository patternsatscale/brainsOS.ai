"""Tests for OKFNote models and YAML frontmatter serialization."""

from titan_memory.okf.models import OKFNote


def test_okf_note_creation():
    note = OKFNote(
        rel_path="knowledge/test.md",
        title="Test Note",
        note_type="knowledge",
        tags=["ai", "titan"],
        body="This is a test note body.",
    )
    assert note.title == "Test Note"
    assert note.note_type == "knowledge"
    assert note.tags == ["ai", "titan"]
    assert note.active is True
    assert note.priority == "normal"
    assert note.body == "This is a test note body."


def test_okf_note_serialization_and_parsing():
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
    assert "---" in serialized
    assert "title: Sample Rule" in serialized
    assert "priority: high" in serialized

    parsed = OKFNote.parse("rules/sample_rule.md", serialized)
    assert parsed.title == original.title
    assert parsed.note_type == original.note_type
    assert parsed.tags == original.tags
    assert parsed.active is True
    assert parsed.priority == "high"
    assert parsed.body == original.body


def test_okf_note_title_inference_from_header():
    raw = """---
type: knowledge
tags:
  - test
---

# Inferred Header Title

Note content goes here.
"""
    note = OKFNote.parse("knowledge/inferred.md", raw)
    assert note.title == "Inferred Header Title"
    assert note.tags == ["test"]
    assert "Note content goes here." in note.body
