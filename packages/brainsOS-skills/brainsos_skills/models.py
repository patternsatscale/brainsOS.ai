"""
Data models representing brainsOS Agent Skills and Planning Archetypes.
"""

from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SkillSourceType(str, Enum):
    BUNDLED = "bundled"
    WORKSPACE = "workspace"
    CUSTOM = "custom"
    DATA = "data"


class SkillMetadata(BaseModel):
    name: str = Field(..., description="Unique lowercase hyphenated skill identifier")
    description: str = Field(..., description="Description explaining what the skill does and when to activate it")
    version: str = Field("0.1.0", description="Semantic version of the skill")
    tags: List[str] = Field(default_factory=list, description="Subsystem/domain categorization tags")
    triggers: List[str] = Field(default_factory=list, description="Explicit slash commands or keyword triggers")
    author: Optional[str] = Field("Patterns at Scale", description="Author or team responsible for the skill")


class Skill(BaseModel):
    metadata: SkillMetadata
    markdown_body: str = Field(..., description="The main markdown instructional body (without YAML frontmatter)")
    file_path: Optional[Path] = Field(None, description="Absolute or relative path to the SKILL.md file")
    source_type: SkillSourceType = Field(SkillSourceType.BUNDLED, description="Origin source of the skill")

    @property
    def name(self) -> str:
        return self.metadata.name

    @property
    def description(self) -> str:
        return self.metadata.description

    @property
    def triggers(self) -> List[str]:
        return self.metadata.triggers

    def matches_trigger(self, prompt: str) -> bool:
        """Check if a prompt contains any of the skill's triggers."""
        lower_prompt = prompt.lower().strip()
        # Direct check on skill name (e.g. /plan:design or plan-design)
        if f"/{self.name}" in lower_prompt or self.name in lower_prompt:
            return True
        for trigger in self.metadata.triggers:
            if trigger.lower() in lower_prompt:
                return True
        return False

    def render_context(self) -> str:
        """Render the complete skill as an instructional block for LLM prompt context."""
        return (
            f"# SKILL: {self.metadata.name.upper()}\n"
            f"> {self.metadata.description}\n\n"
            f"{self.markdown_body.strip()}\n"
        )

    def to_skill_md(self) -> str:
        """Format the skill into standard Antigravity SKILL.md format with YAML frontmatter."""
        import yaml

        frontmatter_dict: Dict[str, Any] = {
            "name": self.metadata.name,
            "description": self.metadata.description,
        }
        if self.metadata.version:
            frontmatter_dict["version"] = self.metadata.version
        if self.metadata.tags:
            frontmatter_dict["tags"] = self.metadata.tags
        if self.metadata.triggers:
            frontmatter_dict["triggers"] = self.metadata.triggers

        yaml_str = yaml.dump(frontmatter_dict, sort_keys=False).strip()
        return f"---\n{yaml_str}\n---\n\n{self.markdown_body.strip()}\n"
