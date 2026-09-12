"""Tests for Rule 1 (Memory Purity) enforcement and path safety."""

import os
import pytest
from titan_memory.okf.purity import resolve_safe_path, validate_purity


def test_path_traversal_blocked(tmp_path):
    root_dir = str(tmp_path)
    with pytest.raises(ValueError, match="traverses outside memory root"):
        resolve_safe_path(root_dir, "../outside.md")

    with pytest.raises(ValueError, match="traverses outside memory root"):
        resolve_safe_path(root_dir, "knowledge/../../outside.md")


def test_safe_path_resolution(tmp_path):
    root_dir = str(tmp_path)
    safe = resolve_safe_path(root_dir, "knowledge/note.md")
    assert safe == os.path.join(root_dir, "knowledge", "note.md")


def test_purity_validation_clean(tmp_path):
    root_dir = str(tmp_path)
    k_dir = tmp_path / "knowledge"
    k_dir.mkdir()
    (k_dir / "note.md").write_text("# Pure Note", encoding="utf-8")
    (k_dir / ".gitkeep").write_text("", encoding="utf-8")

    is_pure, violations = validate_purity(root_dir)
    assert is_pure is True
    assert len(violations) == 0


def test_purity_validation_detects_forbidden_files(tmp_path):
    root_dir = str(tmp_path)
    (tmp_path / "index.db").write_text("dummy sqlite", encoding="utf-8")
    (tmp_path / "cache.pyc").write_bytes(b"\x00\x01")
    (tmp_path / "node_modules").mkdir()

    is_pure, violations = validate_purity(root_dir)
    assert is_pure is False
    assert len(violations) >= 3
