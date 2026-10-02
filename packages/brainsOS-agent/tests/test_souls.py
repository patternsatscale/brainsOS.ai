"""Unit tests for centralized SOUL persona architecture and cascading fallback resolver."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from brainsos_agent.models import AgentProfile
from brainsos_agent.souls import (
    SoulNotFoundError,
    get_soul_path,
    normalize_soul_name,
    resolve_soul,
)


@pytest.fixture
def souls_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Fixture providing isolated data/souls and config/default_souls directories."""
    monkeypatch.delenv("BRAINSOS_DATA_DIR", raising=False)
    monkeypatch.delenv("BRAINSOS_SOULS_DIR", raising=False)
    data_souls = tmp_path / "data" / "souls"
    config_default_souls = tmp_path / "config" / "default_souls"
    data_souls.mkdir(parents=True, exist_ok=True)
    config_default_souls.mkdir(parents=True, exist_ok=True)

    # Seed default souls
    (config_default_souls / "marvin.md").write_text("Default baseline Marvin persona", encoding="utf-8")
    (config_default_souls / "bawtford.md").write_text("Default baseline Bawtford persona", encoding="utf-8")
    (config_default_souls / "bawtford.web-developer.md").write_text(
        "Default baseline Bawtford Web Developer sub-agent persona", encoding="utf-8"
    )

    return {
        "root": tmp_path,
        "data_souls": data_souls,
        "default_souls": config_default_souls,
    }


def test_normalize_soul_name():
    """Verify soul names are canonicalized to dot-namespaced lowercase without .md extension."""
    assert normalize_soul_name("Bawtford") == "bawtford"
    assert normalize_soul_name("bawtford.md") == "bawtford"
    assert normalize_soul_name("Bawtford.Web-Developer.md") == "bawtford.web-developer"
    assert normalize_soul_name("  marvin  ") == "marvin"


def test_fallback_to_default_souls(souls_env):
    """Verify fallback to config/default_souls when data/souls lacks the file."""
    root = souls_env["root"]
    path = get_soul_path("marvin", base_dir=root)
    assert path == souls_env["default_souls"] / "marvin.md"
    assert resolve_soul("marvin", base_dir=root) == "Default baseline Marvin persona"


def test_runtime_override_in_data_souls(souls_env):
    """Verify live override in data/souls takes precedence over config/default_souls."""
    root = souls_env["root"]
    # Write live custom override
    (souls_env["data_souls"] / "marvin.md").write_text("Live customized Marvin persona", encoding="utf-8")

    path = get_soul_path("marvin", base_dir=root)
    assert path == souls_env["data_souls"] / "marvin.md"
    assert resolve_soul("marvin", base_dir=root) == "Live customized Marvin persona"


def test_dot_namespaced_subagent_resolution(souls_env):
    """Verify subagent dot-namespacing (bawtford.web-developer) resolves without nested folders."""
    root = souls_env["root"]
    path = get_soul_path("bawtford.web-developer", base_dir=root)
    assert path == souls_env["default_souls"] / "bawtford.web-developer.md"
    assert "Web Developer" in resolve_soul("bawtford.web-developer", base_dir=root)


def test_case_insensitive_resolution(souls_env):
    """Verify case-insensitive soul name resolution."""
    root = souls_env["root"]
    path = get_soul_path("Bawtford.Web-Developer", base_dir=root)
    assert path == souls_env["default_souls"] / "bawtford.web-developer.md"


def test_missing_soul_raises_soul_not_found_error(souls_env):
    """Verify missing soul raises SoulNotFoundError with actionable error message."""
    root = souls_env["root"]
    with pytest.raises(SoulNotFoundError) as exc_info:
        get_soul_path("non_existent_soul", base_dir=root)

    assert "Soul 'non_existent_soul' could not be resolved in /data/souls/ or config/default_souls/" in str(
        exc_info.value
    )


def test_environment_variable_path_overrides(tmp_path: Path):
    """Verify BRAINSOS_SOULS_DIR and BRAINSOS_DEFAULT_SOULS_DIR environment variable overrides."""
    custom_data = tmp_path / "custom_data_souls"
    custom_default = tmp_path / "custom_default_souls"
    custom_data.mkdir(parents=True, exist_ok=True)
    custom_default.mkdir(parents=True, exist_ok=True)

    (custom_default / "custom.md").write_text("Default custom soul", encoding="utf-8")
    (custom_data / "custom.md").write_text("Overridden custom soul", encoding="utf-8")

    orig_souls = os.environ.get("BRAINSOS_SOULS_DIR")
    orig_default = os.environ.get("BRAINSOS_DEFAULT_SOULS_DIR")

    try:
        os.environ["BRAINSOS_SOULS_DIR"] = str(custom_data)
        os.environ["BRAINSOS_DEFAULT_SOULS_DIR"] = str(custom_default)

        # 1. Override in custom_data takes precedence
        assert resolve_soul("custom") == "Overridden custom soul"

        # 2. If removed from custom_data, falls back to custom_default
        (custom_data / "custom.md").unlink()
        assert resolve_soul("custom") == "Default custom soul"
    finally:
        if orig_souls is not None:
            os.environ["BRAINSOS_SOULS_DIR"] = orig_souls
        else:
            os.environ.pop("BRAINSOS_SOULS_DIR", None)

        if orig_default is not None:
            os.environ["BRAINSOS_DEFAULT_SOULS_DIR"] = orig_default
        else:
            os.environ.pop("BRAINSOS_DEFAULT_SOULS_DIR", None)


def test_agent_profile_with_soul_and_manifest_dict(souls_env):
    """Verify AgentProfile parses soul field and supports dictionary manifest schema."""
    root = souls_env["root"]
    manifest_yaml = """
agents:
  bawtford:
    name: "Bawtford"
    runner: "hermes"
    soul: "bawtford"
    enabled: true

  bawtford-web:
    name: "Bawtford Web Developer"
    runner: "claude-sdk"
    soul: "bawtford.web-developer"
    enabled: true

  marvin:
    name: "Marvin"
    runner: "hermes"
    enabled: true
"""
    profiles = AgentProfile.from_manifest_yaml(manifest_yaml, base_path=root)
    assert isinstance(profiles, list)
    assert len(profiles) == 3

    bawtford = next(p for p in profiles if p.id == "bawtford")
    assert bawtford.soul == "bawtford"
    assert bawtford.soul_path == souls_env["default_souls"] / "bawtford.md"
    assert bawtford.runtime == "hermes"

    bawtford_web = next(p for p in profiles if p.id == "bawtford-web")
    assert bawtford_web.soul == "bawtford.web-developer"
    assert bawtford_web.soul_path == souls_env["default_souls"] / "bawtford.web-developer.md"
    assert bawtford_web.runtime == "claude-sdk"

    # Marvin defaulted soul to agent id ("marvin")
    marvin = next(p for p in profiles if p.id == "marvin")
    assert marvin.soul == "marvin"
    assert marvin.soul_path == souls_env["default_souls"] / "marvin.md"
