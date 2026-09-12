"""Tests for OKFEngine CRUD, keyword search, and prompt synthesis."""

import os
import pytest
from titan_memory.okf.engine import OKFEngine


def test_write_and_read_note(tmp_path):
    engine = OKFEngine(root_dir=str(tmp_path))

    note = engine.write_note(
        rel_path="knowledge/architecture.md",
        content="Project Titan runs on NVIDIA GB10 hardware.",
        title="Architecture",
        tags=["hw", "gb10"],
        priority="high",
    )
    assert note.title == "Architecture"
    assert os.path.exists(os.path.join(str(tmp_path), "knowledge", "architecture.md"))

    loaded = engine.read_note("knowledge/architecture.md")
    assert loaded.title == "Architecture"
    assert "NVIDIA GB10" in loaded.body
    assert loaded.tags == ["hw", "gb10"]


def test_write_rejects_non_markdown(tmp_path):
    engine = OKFEngine(root_dir=str(tmp_path))
    with pytest.raises(ValueError, match="must end with .md"):
        engine.write_note(
            rel_path="knowledge/data.sqlite",
            content="bad data",
        )


def test_write_rejects_binary(tmp_path):
    engine = OKFEngine(root_dir=str(tmp_path))
    with pytest.raises(ValueError, match="binary data cannot be written"):
        engine.write_note(
            rel_path="knowledge/blob.md",
            content="bad \x00 binary",
        )


def test_list_and_search_notes(tmp_path):
    engine = OKFEngine(root_dir=str(tmp_path))

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
    assert len(notes) == 2

    # Search keyword
    football_matches = engine.search("tactical")
    assert len(football_matches) == 1
    assert football_matches[0]["title"] == "Football Guide"

    tag_matches = engine.search("wellness")
    assert len(tag_matches) == 1
    assert tag_matches[0]["title"] == "Pet Care"


def test_active_rules_synthesis(tmp_path):
    engine = OKFEngine(root_dir=str(tmp_path))

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
    assert "OPERATOR RULES & GUARDRAILS" in context
    assert "Rule 1: Unprivileged" in context
    assert "Rule 2: Inactive" not in context
