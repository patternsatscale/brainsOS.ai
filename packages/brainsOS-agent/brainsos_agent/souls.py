"""Centralized SOUL Persona Architecture and Cascading Fallback Resolver for brainsOS."""

from __future__ import annotations

import os
from pathlib import Path


class SoulNotFoundError(FileNotFoundError):
    """Raised when an agent soul cannot be resolved in data/souls/ or config/default_souls/."""

    pass


def _find_repo_root(start: Path | None = None) -> Path:
    """Discovers the root directory of the repository or appliance installation."""
    if "BRAINSOS_ROOT" in os.environ:
        return Path(os.environ["BRAINSOS_ROOT"]).resolve()

    # Try upward traversal from start path or caller module
    search_starts = [start] if start else [Path.cwd(), Path(__file__).resolve().parent]
    for cur in search_starts:
        if cur is None:
            continue
        cur = cur.resolve()
        for parent in [cur, *cur.parents]:
            if (
                (parent / "config" / "default_souls").is_dir()
                or (parent / "config" / "default_settings").is_dir()
                or (parent / ".git").exists()
            ):
                return parent

    return Path.cwd().resolve()


def normalize_soul_name(soul_name: str | Path) -> str:
    """Normalizes a soul name to canonical dot-namespaced lowercase without .md extension."""
    name_str = str(soul_name).strip()
    if name_str.lower().endswith(".md"):
        name_str = name_str[:-3]
    return name_str.strip().lower()


def get_soul_path(soul_name: str | Path, base_dir: Path | str | None = None) -> Path:
    """Resolves the canonical Path to an agent persona (SOUL.md) using cascading fallback.

    Resolution Strategy:
    1. /data/souls/{soul_name}.md (Live custom soul override)
    2. config/default_souls/{soul_name}.md (Baseline default seed soul)
    3. SoulNotFoundError

    Path overrides can be set via environment variables:
    - BRAINSOS_SOULS_DIR (default: base_dir/data/souls)
    - BRAINSOS_DEFAULT_SOULS_DIR (default: base_dir/config/default_souls)
    """
    base = Path(base_dir).resolve() if base_dir else _find_repo_root()

    # Determine runtime data souls directory
    souls_dir_env = os.environ.get("BRAINSOS_SOULS_DIR")
    if souls_dir_env:
        souls_dir = Path(souls_dir_env)
        if not souls_dir.is_absolute():
            souls_dir = (base / souls_dir).resolve()
    else:
        souls_dir = (base / "data" / "souls").resolve()

    # Determine config default souls directory
    default_souls_dir_env = os.environ.get("BRAINSOS_DEFAULT_SOULS_DIR")
    if default_souls_dir_env:
        default_souls_dir = Path(default_souls_dir_env)
        if not default_souls_dir.is_absolute():
            default_souls_dir = (base / default_souls_dir).resolve()
    else:
        default_souls_dir = (base / "config" / "default_souls").resolve()

    # Check if soul_name is already a direct existing file path
    p = Path(soul_name)
    if p.is_file() and p.stat().st_size > 0:
        return p.resolve()
    if (base / p).is_file() and (base / p).stat().st_size > 0:
        return (base / p).resolve()

    normalized = normalize_soul_name(soul_name)
    filename = f"{normalized}.md"

    # 1. Check live custom soul override in data/souls/
    live_path = souls_dir / filename
    if live_path.is_file() and live_path.stat().st_size > 0:
        return live_path.resolve()

    # 2. Check baseline default soul in config/default_souls/
    default_path = default_souls_dir / filename
    if default_path.is_file() and default_path.stat().st_size > 0:
        return default_path.resolve()

    # 3. Not found in either location
    raise SoulNotFoundError(
        f"Soul '{soul_name}' could not be resolved in /data/souls/ or config/default_souls/ "
        f"(checked '{live_path}' and '{default_path}')"
    )


def resolve_soul(soul_name: str | Path, base_dir: Path | str | None = None) -> str:
    """Resolves and loads the persona markdown content for the specified agent soul."""
    soul_path = get_soul_path(soul_name, base_dir=base_dir)
    return soul_path.read_text(encoding="utf-8").strip()
