"""Inviolable Rule 1 (Memory Plane Purity) Validators and Path Guardrails."""

from __future__ import annotations

import os

FORBIDDEN_EXTENSIONS = {
    ".db",
    ".sqlite",
    ".sqlite3",
    ".pyc",
    ".pyo",
    ".so",
    ".bin",
    ".tar",
    ".gz",
    ".zip",
    ".lock",
    ".log",
    ".tmp",
    ".bak",
}

FORBIDDEN_DIRECTORIES = {"__pycache__", "node_modules", ".cache", ".venv", "venv", ".git"}


ALLOWED_DOTFILES = {".gitkeep"}


def resolve_safe_path(root_dir: str, rel_path: str) -> str:
    """Resolve target path via realpath + commonpath, rejecting symlinks and traversal."""
    real_root = os.path.realpath(root_dir)
    clean_rel = rel_path.strip().lstrip("/")
    candidate = os.path.join(real_root, clean_rel)
    real_path = os.path.realpath(candidate)
    if os.path.commonpath([real_root, real_path]) != real_root:
        raise ValueError(f"Access denied: path '{rel_path}' traverses outside memory root.")
    return real_path


def validate_purity(root_dir: str) -> tuple[bool, list[str]]:
    """Scan root_dir to verify strict adherence to Rule 1 (Memory Purity)."""
    violations = []
    real_root = os.path.realpath(root_dir)
    if not os.path.exists(real_root):
        return (True, [])

    for current_root, dirs, files in os.walk(real_root, followlinks=False):
        rel_dir = os.path.relpath(current_root, real_root)

        for d in dirs:
            d_path = os.path.join(current_root, d)
            if os.path.islink(d_path):
                violations.append(f"Forbidden symlink directory '{d}' inside {rel_dir}")
            elif d in FORBIDDEN_DIRECTORIES or d.startswith("."):
                violations.append(f"Forbidden directory '{d}' inside {rel_dir}")

        for f in files:
            f_path = os.path.join(current_root, f)
            if os.path.islink(f_path):
                violations.append(f"Forbidden symlink file '{f}' inside {rel_dir}")
                continue
            if f in ALLOWED_DOTFILES:
                continue
            if f.startswith("."):
                violations.append(f"Forbidden hidden dotfile '{f}' inside {rel_dir}")
                continue
            _, ext = os.path.splitext(f)
            ext_lower = ext.lower()

            if ext_lower in FORBIDDEN_EXTENSIONS:
                violations.append(f"Forbidden file type '{f}' ({ext_lower}) in {rel_dir}")
            elif ext_lower != ".md":
                violations.append(f"Non-markdown file '{f}' in {rel_dir}")

    return (len(violations) == 0, violations)
