"""
Registry for brainsOS Agent Skills and Planning Archetypes.
"""

from typing import Dict, List, Optional

from brainsos_skills.models import Skill


class SkillRegistry:
    """Central registry storing and resolving brainsOS skills."""

    def __init__(self):
        self._skills: Dict[str, Skill] = {}

    def register(self, skill: Skill, overwrite: bool = True) -> None:
        """Register a new skill into the registry."""
        if skill.name in self._skills and not overwrite:
            raise KeyError(f"Skill '{skill.name}' is already registered.")
        self._skills[skill.name] = skill

    def get(self, name: str) -> Optional[Skill]:
        """Retrieve a skill by its unique identifier."""
        return self._skills.get(name)

    def list_all(self) -> List[Skill]:
        """Return all registered skills sorted by name."""
        return sorted(self._skills.values(), key=lambda s: s.name)

    def find_matching(self, prompt: str) -> List[Skill]:
        """Find all skills that match a given user prompt or slash command."""
        return [skill for skill in self._skills.values() if skill.matches_trigger(prompt)]

    def get_by_tag(self, tag: str) -> List[Skill]:
        """Retrieve all skills tagged with a specific domain tag."""
        return [skill for skill in self._skills.values() if tag in skill.metadata.tags]

    def clear(self) -> None:
        """Clear all registered skills."""
        self._skills.clear()

    def __len__(self) -> int:
        return len(self._skills)

    def __contains__(self, name: str) -> bool:
        return name in self._skills
