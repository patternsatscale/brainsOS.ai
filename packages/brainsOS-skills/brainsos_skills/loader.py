"""
Discovery and loading utilities for brainsOS skills.
"""

import os
from pathlib import Path
from typing import List, Optional

from brainsos_skills.models import Skill, SkillSourceType
from brainsos_skills.registry import SkillRegistry
from brainsos_skills.validator import validate_skill_file

BUNDLED_SKILLS_DIR = Path(__file__).parent / "bundled"


def discover_skills_in_dir(directory: Path, source_type: SkillSourceType = SkillSourceType.CUSTOM) -> List[Skill]:
    """
    Recursively discover all SKILL.md files within a directory.
    Standard layout: <directory>/<skill_name>/SKILL.md
    """
    skills: List[Skill] = []
    if not directory.exists() or not directory.is_dir():
        return skills

    # Search for SKILL.md in direct subdirectories or root
    for skill_file in directory.glob("**/SKILL.md"):
        valid, msg, skill = validate_skill_file(skill_file, source_type=source_type)
        if valid and skill is not None:
            skills.append(skill)

    return skills


def load_bundled_skills(registry: Optional[SkillRegistry] = None) -> SkillRegistry:
    """
    Load all canonical bundled skills into the provided or new registry.
    """
    if registry is None:
        registry = SkillRegistry()

    bundled = discover_skills_in_dir(BUNDLED_SKILLS_DIR, source_type=SkillSourceType.BUNDLED)
    for skill in bundled:
        registry.register(skill, overwrite=True)

    return registry


def load_data_skills(data_skills_dir: Path, registry: Optional[SkillRegistry] = None) -> SkillRegistry:
    """
    Load live/proprietary fleet skills from data/skills/ (or $BRAINSOS_DATA_DIR/skills/).
    These take precedence over bundled/default skills.
    """
    if registry is None:
        registry = SkillRegistry()

    data_skills = discover_skills_in_dir(data_skills_dir, source_type=SkillSourceType.DATA)
    for skill in data_skills:
        registry.register(skill, overwrite=True)

    return registry


def load_workspace_skills(workspace_root: Path, registry: Optional[SkillRegistry] = None) -> SkillRegistry:
    """
    Load skills from a project's .agents/skills/ directory.
    """
    if registry is None:
        registry = SkillRegistry()

    skills_dir = workspace_root / ".agents" / "skills"
    workspace_skills = discover_skills_in_dir(skills_dir, source_type=SkillSourceType.WORKSPACE)
    for skill in workspace_skills:
        registry.register(skill, overwrite=True)

    return registry


def load_hierarchical_skills(
    repo_root: Optional[Path] = None,
    data_dir: Optional[Path] = None,
    registry: Optional[SkillRegistry] = None,
) -> SkillRegistry:
    """
    Load skills with brainsOS hierarchy:
    1. Base/Bundled package skills (or config/default_skills if present in repo)
    2. Data Plane skills from $BRAINSOS_DATA_DIR/skills or data/skills (overriding/extending defaults)
    """
    if registry is None:
        registry = SkillRegistry()

    # 1. Base skills: check repo_root / config / default_skills, else package bundled
    if repo_root and (repo_root / "config" / "default_skills").is_dir():
        default_skills = discover_skills_in_dir(repo_root / "config" / "default_skills", source_type=SkillSourceType.BUNDLED)
        for skill in default_skills:
            registry.register(skill, overwrite=True)
    else:
        load_bundled_skills(registry)

    # 2. Data plane skills (stateful/proprietary IP)
    resolved_data_dir = data_dir
    if resolved_data_dir is None:
        env_data = os.environ.get("BRAINSOS_DATA_DIR")
        if env_data:
            resolved_data_dir = Path(env_data) / "skills"
        elif repo_root:
            resolved_data_dir = repo_root / "data" / "skills"
        else:
            resolved_data_dir = Path("data/skills")

    if resolved_data_dir and resolved_data_dir.is_dir():
        load_data_skills(resolved_data_dir, registry)

    return registry


def sync_skills_to_workspace(registry: SkillRegistry, target_dir: Path, clean_orphans: bool = True) -> List[Path]:
    """
    Export all skills in the registry to standard Antigravity workspace folders:
    <target_dir>/<skill_name>/SKILL.md
    """
    import shutil

    written_files: List[Path] = []
    target_dir.mkdir(parents=True, exist_ok=True)

    active_names = {skill.name for skill in registry.list_all()}

    if clean_orphans:
        for child in target_dir.iterdir():
            if child.is_dir() and child.name not in active_names and (child / "SKILL.md").exists():
                shutil.rmtree(child)

    for skill in registry.list_all():
        skill_dir = target_dir / skill.name
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(skill.to_skill_md(), encoding="utf-8")
        written_files.append(skill_file)

    return written_files
