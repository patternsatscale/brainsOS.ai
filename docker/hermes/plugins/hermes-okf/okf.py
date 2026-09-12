"""Hermes Plugin Compatibility Shim for titan_memory (OKF Engine).

This module re-exports core classes and utilities from packages/titan_memory
to ensure 100% backward compatibility with upstream Hermes plugins.
"""

from __future__ import annotations

from titan_memory.okf import (
    FORBIDDEN_DIRECTORIES,
    FORBIDDEN_EXTENSIONS,
    HermesOKF,
    OKFEngine,
    OKFNote,
    get_context_window,
    get_memory_dir,
    resolve_safe_path,
    validate_purity,
)

__all__ = [
    "HermesOKF",
    "OKFEngine",
    "OKFNote",
    "get_memory_dir",
    "get_context_window",
    "FORBIDDEN_EXTENSIONS",
    "FORBIDDEN_DIRECTORIES",
    "resolve_safe_path",
    "validate_purity",
]
