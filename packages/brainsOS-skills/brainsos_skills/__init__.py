"""
brainsOS-skills: Autonomous Agent Skills & Planning Protocol Engine.
"""

from brainsos_skills.loader import (
    BUNDLED_SKILLS_DIR,
    discover_skills_in_dir,
    load_bundled_skills,
    load_workspace_skills,
    sync_skills_to_workspace,
)
from brainsos_skills.models import Skill, SkillMetadata, SkillSourceType
from brainsos_skills.registry import SkillRegistry
from brainsos_skills.validator import parse_skill_text, validate_skill_file

__version__ = "0.1.0"
__all__ = [
    "Skill",
    "SkillMetadata",
    "SkillSourceType",
    "SkillRegistry",
    "load_bundled_skills",
    "load_workspace_skills",
    "discover_skills_in_dir",
    "sync_skills_to_workspace",
    "parse_skill_text",
    "validate_skill_file",
    "BUNDLED_SKILLS_DIR",
]
