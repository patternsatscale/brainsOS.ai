"""
Unit tests for brainsOS-skills package.
"""

import pytest
from pathlib import Path
from brainsos_skills.models import Skill, SkillMetadata, SkillSourceType
from brainsos_skills.validator import parse_skill_text, validate_skill_file
from brainsos_skills.registry import SkillRegistry
from brainsos_skills.loader import load_bundled_skills, sync_skills_to_workspace, BUNDLED_SKILLS_DIR


def test_parse_valid_skill():
    content = """---
name: test-skill
description: "A test skill for validation"
version: "1.0.0"
tags: ["test", "demo"]
triggers: ["/test", "test command"]
---

# Test Skill
Procedural instructions go here.
"""
    skill = parse_skill_text(content)
    assert skill.name == "test-skill"
    assert skill.description == "A test skill for validation"
    assert skill.metadata.version == "1.0.0"
    assert "test" in skill.metadata.tags
    assert skill.matches_trigger("/test")
    assert skill.matches_trigger("run test command now")
    assert not skill.matches_trigger("something completely unrelated")


def test_parse_invalid_frontmatter():
    with pytest.raises(ValueError, match="Missing leading YAML frontmatter"):
        parse_skill_text("Just plain markdown without frontmatter")

    with pytest.raises(ValueError, match="missing required string field: 'name'"):
        parse_skill_text("---\ndescription: 'No name'\n---\nBody")

    with pytest.raises(ValueError, match="must be lowercase, dot-namespaced, or hyphenated"):
        parse_skill_text("---\nname: Invalid_Name!\ndescription: 'Desc'\n---\nBody")


def test_registry_operations():
    registry = SkillRegistry()
    assert len(registry) == 0

    meta = SkillMetadata(name="skill-a", description="Skill A description", triggers=["/a"])
    skill_a = Skill(metadata=meta, markdown_body="Body A")
    registry.register(skill_a)

    assert len(registry) == 1
    assert "skill-a" in registry
    assert registry.get("skill-a") is skill_a

    meta_b = SkillMetadata(name="skill-b", description="Skill B description", triggers=["/b"])
    skill_b = Skill(metadata=meta_b, markdown_body="Body B")
    registry.register(skill_b)

    assert len(registry) == 2
    matching = registry.find_matching("/b please")
    assert len(matching) == 1
    assert matching[0].name == "skill-b"


def test_bundled_skills_are_valid():
    """Ensure all bundled canonical skills load and parse without any errors."""
    assert BUNDLED_SKILLS_DIR.exists()
    registry = load_bundled_skills()

    expected_skills = {"plan", "plan.epics", "plan.ux", "plan.copy", "agents-discipline"}
    for name in expected_skills:
        skill = registry.get(name)
        assert skill is not None, f"Expected bundled skill '{name}' was not loaded!"
        assert skill.source_type == SkillSourceType.BUNDLED
        assert len(skill.markdown_body) > 50

    # Test router triggers
    plan_router = registry.get("plan")
    assert plan_router.matches_trigger("/plan")
    assert plan_router.matches_trigger("plan next steps")

    # Test dedicated epic planner triggers
    plan_epics = registry.get("plan.epics")
    assert plan_epics.matches_trigger("/plan:epics")
    assert plan_epics.matches_trigger("/plan.epics")
    assert plan_epics.matches_trigger("/plan:epic")
    assert plan_epics.matches_trigger("/plan.epic")
    assert plan_epics.matches_trigger("plan epic for portal")

    # Test UX planner triggers
    plan_ux = registry.get("plan.ux")
    assert plan_ux.matches_trigger("/plan:ux")
    assert plan_ux.matches_trigger("/plan.ux")
    assert plan_ux.matches_trigger("/plan:design")
    assert plan_ux.matches_trigger("plan ux for dashboard")

    # Test Copy planner triggers
    plan_copy = registry.get("plan.copy")
    assert plan_copy.matches_trigger("/plan:copy")
    assert plan_copy.matches_trigger("/plan.copy")
    assert plan_copy.matches_trigger("/plan:pr")
    assert plan_copy.matches_trigger("plan copy for release")


def test_sync_skills_to_workspace(tmp_path: Path):
    registry = load_bundled_skills()
    target_dir = tmp_path / "skills"

    written = sync_skills_to_workspace(registry, target_dir)
    assert len(written) >= 5

    for path in written:
        assert path.exists()
        valid, msg, loaded_skill = validate_skill_file(path)
        assert valid, f"Exported skill file {path} failed validation: {msg}"
        assert loaded_skill is not None


def test_hierarchical_loading_with_data_override(tmp_path: Path):
    from brainsos_skills.loader import load_hierarchical_skills

    # Create fake repo with config/default_skills
    repo_dir = tmp_path / "repo"
    default_dir = repo_dir / "config" / "default_skills" / "custom.test"
    default_dir.mkdir(parents=True)
    (default_dir / "SKILL.md").write_text("""---
name: custom.test
description: "Default baseline skill"
version: "1.0.0"
---
# Baseline
Original body
""", encoding="utf-8")

    # Create fake data plane with proprietary override
    data_dir = tmp_path / "data" / "skills" / "custom.test"
    data_dir.mkdir(parents=True)
    (data_dir / "SKILL.md").write_text("""---
name: custom.test
description: "Proprietary override skill"
version: "2.0.0"
---
# Proprietary
Custom body
""", encoding="utf-8")

    registry = load_hierarchical_skills(repo_root=repo_dir, data_dir=tmp_path / "data" / "skills")
    skill = registry.get("custom.test")
    assert skill is not None
    assert skill.metadata.version == "2.0.0"
    assert skill.description == "Proprietary override skill"
    assert skill.source_type == SkillSourceType.DATA

