"""brainsos_agent.config — Central path and environment configuration resolver."""

from __future__ import annotations

import os
from pathlib import Path


def get_data_dir() -> Path:
    """Return root runtime data directory from BRAINSOS_DATA_DIR or default to ./data."""
    return Path(os.getenv("BRAINSOS_DATA_DIR", "./data")).resolve()


def get_souls_dir() -> Path:
    """Return active souls directory from BRAINSOS_SOULS_DIR or data_dir / souls."""
    return Path(os.getenv("BRAINSOS_SOULS_DIR", get_data_dir() / "souls")).resolve()


def get_memories_dir() -> Path:
    """Return active memories directory from BRAINSOS_MEMORIES_DIR or data_dir / agent_memories."""
    return Path(
        os.getenv(
            "BRAINSOS_MEMORIES_DIR",
            os.getenv("BRAINSOS_AGENT_MEMORIES_DIR", get_data_dir() / "agent_memories"),
        )
    ).resolve()


def get_workspaces_dir() -> Path:
    """Return active workspaces directory from BRAINSOS_WORKSPACES_DIR or data_dir / agent_workspaces."""
    return Path(
        os.getenv(
            "BRAINSOS_WORKSPACES_DIR",
            os.getenv("BRAINSOS_AGENT_WORKSPACES_DIR", get_data_dir() / "agent_workspaces"),
        )
    ).resolve()


def get_settings_dir() -> Path:
    """Return active settings directory from BRAINSOS_SETTINGS_DIR or data_dir / settings."""
    return Path(os.getenv("BRAINSOS_SETTINGS_DIR", get_data_dir() / "settings")).resolve()


def get_agent_apps_dir() -> Path:
    """Return active agent apps directory from BRAINSOS_AGENT_APPS_DIR or data_dir / agent_apps."""
    return Path(os.getenv("BRAINSOS_AGENT_APPS_DIR", get_data_dir() / "agent_apps")).resolve()


def get_runners_dir() -> Path:
    """Return active runners directory from BRAINSOS_RUNNERS_DIR or data_dir / runners."""
    return Path(os.getenv("BRAINSOS_RUNNERS_DIR", get_data_dir() / "runners")).resolve()


def get_comms_dir() -> Path:
    """Return active comms directory from BRAINSOS_COMMS_DIR or data_dir / comms."""
    return Path(os.getenv("BRAINSOS_COMMS_DIR", get_data_dir() / "comms")).resolve()


def get_control_plane_dir() -> Path:
    """Return active control plane directory from BRAINSOS_CONTROL_PLANE_DIR or data_dir / control_plane."""
    return Path(os.getenv("BRAINSOS_CONTROL_PLANE_DIR", get_data_dir() / "control_plane")).resolve()


def resolve_manifest_path(explicit_path: str | Path | None = None) -> Path:
    """Resolves the canonical path to agents.yaml manifest across core and decoupled setups."""
    if explicit_path:
        p = Path(explicit_path)
        if p.exists():
            return p.resolve()
    for cand in [
        get_settings_dir() / "agents.yaml",
        get_data_dir() / "settings" / "agents.yaml",
        Path("data/settings/agents.yaml"),
        Path("config/default_settings/agents.yaml"),
        Path("config/agents.yaml"),
    ]:
        if cand.exists():
            return cand.resolve()
    return Path(explicit_path or "config/default_settings/agents.yaml").resolve()

