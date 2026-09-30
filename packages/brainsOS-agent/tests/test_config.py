"""Unit tests for brainsos_agent.config and BRAINSOS_DATA_DIR path resolution."""

from pathlib import Path

from brainsos_agent.config import (
    get_agent_apps_dir,
    get_comms_dir,
    get_data_dir,
    get_memories_dir,
    get_runners_dir,
    get_settings_dir,
    get_souls_dir,
    get_workspaces_dir,
)
from brainsos_agent.models import AgentProfile
from brainsos_agent.souls import get_soul_path, resolve_soul


def test_default_path_resolvers(monkeypatch):
    """Verify default paths resolve against ./data when no env vars are set."""
    monkeypatch.delenv("BRAINSOS_DATA_DIR", raising=False)
    monkeypatch.delenv("BRAINSOS_SOULS_DIR", raising=False)
    monkeypatch.delenv("BRAINSOS_MEMORIES_DIR", raising=False)
    monkeypatch.delenv("BRAINSOS_AGENT_MEMORIES_DIR", raising=False)
    monkeypatch.delenv("BRAINSOS_WORKSPACES_DIR", raising=False)
    monkeypatch.delenv("BRAINSOS_AGENT_WORKSPACES_DIR", raising=False)
    monkeypatch.delenv("BRAINSOS_SETTINGS_DIR", raising=False)
    monkeypatch.delenv("BRAINSOS_AGENT_APPS_DIR", raising=False)
    monkeypatch.delenv("BRAINSOS_RUNNERS_DIR", raising=False)
    monkeypatch.delenv("BRAINSOS_COMMS_DIR", raising=False)

    data_dir = get_data_dir()
    assert data_dir == Path("./data").resolve()
    assert get_souls_dir() == data_dir / "souls"
    assert get_memories_dir() == data_dir / "agent_memories"
    assert get_workspaces_dir() == data_dir / "agent_workspaces"
    assert get_settings_dir() == data_dir / "settings"
    assert get_agent_apps_dir() == data_dir / "agent_apps"
    assert get_runners_dir() == data_dir / "runners"
    assert get_comms_dir() == data_dir / "comms"


def test_external_data_dir_override(monkeypatch, tmp_path):
    """Verify setting BRAINSOS_DATA_DIR dynamically shifts all sub-paths to the external directory."""
    ext_data = tmp_path / "external_data_repo"
    ext_data.mkdir()

    monkeypatch.setenv("BRAINSOS_DATA_DIR", str(ext_data))
    monkeypatch.delenv("BRAINSOS_SOULS_DIR", raising=False)
    monkeypatch.delenv("BRAINSOS_MEMORIES_DIR", raising=False)
    monkeypatch.delenv("BRAINSOS_AGENT_MEMORIES_DIR", raising=False)
    monkeypatch.delenv("BRAINSOS_WORKSPACES_DIR", raising=False)
    monkeypatch.delenv("BRAINSOS_AGENT_WORKSPACES_DIR", raising=False)
    monkeypatch.delenv("BRAINSOS_SETTINGS_DIR", raising=False)
    monkeypatch.delenv("BRAINSOS_AGENT_APPS_DIR", raising=False)
    monkeypatch.delenv("BRAINSOS_RUNNERS_DIR", raising=False)
    monkeypatch.delenv("BRAINSOS_COMMS_DIR", raising=False)

    assert get_data_dir() == ext_data.resolve()
    assert get_souls_dir() == ext_data.resolve() / "souls"
    assert get_memories_dir() == ext_data.resolve() / "agent_memories"
    assert get_workspaces_dir() == ext_data.resolve() / "agent_workspaces"
    assert get_settings_dir() == ext_data.resolve() / "settings"
    assert get_agent_apps_dir() == ext_data.resolve() / "agent_apps"
    assert get_runners_dir() == ext_data.resolve() / "runners"
    assert get_comms_dir() == ext_data.resolve() / "comms"


def test_specific_subpath_overrides_take_precedence(monkeypatch, tmp_path):
    """Verify specific directory env vars override BRAINSOS_DATA_DIR."""
    ext_data = tmp_path / "external_data"
    custom_souls = tmp_path / "custom_souls"
    custom_memories = tmp_path / "custom_memories"

    monkeypatch.setenv("BRAINSOS_DATA_DIR", str(ext_data))
    monkeypatch.setenv("BRAINSOS_SOULS_DIR", str(custom_souls))
    monkeypatch.setenv("BRAINSOS_MEMORIES_DIR", str(custom_memories))

    assert get_data_dir() == ext_data.resolve()
    assert get_souls_dir() == custom_souls.resolve()
    assert get_memories_dir() == custom_memories.resolve()
    assert get_workspaces_dir() == ext_data.resolve() / "agent_workspaces"


def test_agent_profile_defaults_with_brainsos_data_dir(monkeypatch, tmp_path):
    """Verify AgentProfile.from_dict uses external paths from BRAINSOS_DATA_DIR."""
    ext_data = tmp_path / "my_fleet_data"
    ext_data.mkdir()

    monkeypatch.setenv("BRAINSOS_DATA_DIR", str(ext_data))
    monkeypatch.delenv("BRAINSOS_MEMORIES_DIR", raising=False)
    monkeypatch.delenv("BRAINSOS_AGENT_MEMORIES_DIR", raising=False)
    monkeypatch.delenv("BRAINSOS_WORKSPACES_DIR", raising=False)
    monkeypatch.delenv("BRAINSOS_AGENT_WORKSPACES_DIR", raising=False)

    profile = AgentProfile.from_dict(
        {
            "name": "Test Agent",
            "id": "test_agent",
            "routing": {
                "email": "test@brainsos.local",
                "runtime": "hermes",
                "model": "test-model",
            },
        }
    )

    assert profile.memory_root == ext_data.resolve() / "agent_memories" / "test_agent"
    assert profile.workspace_root == ext_data.resolve() / "agent_workspaces" / "test_agent"


def test_soul_resolution_from_brainsos_data_dir(monkeypatch, tmp_path):
    """Verify get_soul_path resolves custom souls from BRAINSOS_DATA_DIR/souls."""
    ext_data = tmp_path / "my_fleet_data"
    souls_dir = ext_data / "souls"
    souls_dir.mkdir(parents=True)

    custom_soul = souls_dir / "custom_bot.md"
    custom_soul.write_text("I am Custom Bot from external repo!", encoding="utf-8")

    monkeypatch.setenv("BRAINSOS_DATA_DIR", str(ext_data))
    monkeypatch.delenv("BRAINSOS_SOULS_DIR", raising=False)

    resolved_path = get_soul_path("custom_bot")
    assert resolved_path == custom_soul.resolve()

    content = resolve_soul("custom_bot")
    assert content == "I am Custom Bot from external repo!"
