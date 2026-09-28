"""Inviolable Rule 1 (Memory Plane Purity) Validators and Path Guardrails."""

from __future__ import annotations

import os

FORBIDDEN_EXTENSIONS = {
    ".db", ".sqlite", ".sqlite3", ".pyc", ".pyo", ".so", ".bin",
    ".tar", ".gz", ".zip", ".lock", ".log", ".tmp", ".bak"
}

FORBIDDEN_DIRECTORIES = {
    "__pycache__", "node_modules", ".cache", ".venv", "venv", ".git"
}


def resolve_safe_path(root_dir: str, rel_path: str) -> str:
    """Resolve target path ensuring it does not escape the root directory."""
    clean_rel = os.path.normpath(rel_path.strip().lstrip("/"))
    abs_root = os.path.abspath(root_dir)
    abs_path = os.path.abspath(os.path.join(abs_root, clean_rel))
    if not abs_path.startswith(abs_root):
        raise ValueError(f"Access denied: path '{rel_path}' traverses outside memory root.")
    return abs_path


def validate_purity(root_dir: str) -> tuple[bool, list[str]]:
    """Scan root_dir to verify strict adherence to Rule 1 (Memory Purity)."""
    violations = []
    abs_root = os.path.abspath(root_dir)
    if not os.path.exists(abs_root):
        return (True, [])

    for current_root, dirs, files in os.walk(abs_root):
        rel_dir = os.path.relpath(current_root, abs_root)

        for d in dirs:
            if d in FORBIDDEN_DIRECTORIES:
                violations.append(f"Forbidden directory '{d}' inside {rel_dir}")

        for f in files:
            if f.startswith(".gitkeep"):
                continue
            _, ext = os.path.splitext(f)
            ext_lower = ext.lower()

            if ext_lower in FORBIDDEN_EXTENSIONS:
                violations.append(f"Forbidden file type '{f}' ({ext_lower}) in {rel_dir}")
            elif ext_lower != ".md" and not f.startswith("."):
                violations.append(f"Non-markdown file '{f}' in {rel_dir}")

    return (len(violations) == 0, violations)
