"""Tests for Rule 1 (Memory Purity) enforcement and path safety."""

import os
import tempfile
import unittest

from brainsos_memory.okf.purity import resolve_safe_path, validate_purity


class TestMemoryPurity(unittest.TestCase):
    def test_path_traversal_blocked(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            with self.assertRaises(ValueError):
                resolve_safe_path(tmp_dir, "../outside.md")

            with self.assertRaises(ValueError):
                resolve_safe_path(tmp_dir, "knowledge/../../outside.md")

    def test_safe_path_resolution(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            safe = resolve_safe_path(tmp_dir, "knowledge/note.md")
            self.assertEqual(safe, os.path.join(tmp_dir, "knowledge", "note.md"))

    def test_purity_validation_clean(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            k_dir = os.path.join(tmp_dir, "knowledge")
            os.makedirs(k_dir)
            with open(os.path.join(k_dir, "note.md"), "w", encoding="utf-8") as f:
                f.write("# Pure Note")
            with open(os.path.join(k_dir, ".gitkeep"), "w", encoding="utf-8") as f:
                f.write("")

            is_pure, violations = validate_purity(tmp_dir)
            self.assertTrue(is_pure)
            self.assertEqual(len(violations), 0)

    def test_purity_validation_detects_forbidden_files(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            with open(os.path.join(tmp_dir, "index.db"), "w", encoding="utf-8") as f:
                f.write("dummy sqlite")
            with open(os.path.join(tmp_dir, "cache.pyc"), "wb") as f:
                f.write(b"\x00\x01")
            os.makedirs(os.path.join(tmp_dir, "node_modules"))

            is_pure, violations = validate_purity(tmp_dir)
            self.assertFalse(is_pure)
            self.assertGreaterEqual(len(violations), 3)


if __name__ == "__main__":
    unittest.main()
