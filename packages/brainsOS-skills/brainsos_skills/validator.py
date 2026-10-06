"""
Validation and parsing utilities for brainsOS SKILL.md files.
"""

import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import yaml
from pydantic import ValidationError

from brainsos_skills.models import Skill, SkillMetadata, SkillSourceType

FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


def parse_skill_text(content: str, file_path: Optional[Path] = None, source_type: SkillSourceType = SkillSourceType.BUNDLED) -> Skill:
    """
    Parse a SKILL.md text containing YAML frontmatter and a markdown body.
    """
    match = FRONTMATTER_PATTERN.match(content.strip())
    if not match:
        raise ValueError("Invalid SKILL.md: Missing leading YAML frontmatter delimited by '---'.")

    frontmatter_raw, markdown_body = match.groups()

    try:
        data: Dict[str, Any] = yaml.safe_load(frontmatter_raw) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML frontmatter: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("Frontmatter must be a valid mapping dictionary.")

    name = data.get("name")
    if not name or not isinstance(name, str):
        raise ValueError("Frontmatter missing required string field: 'name'.")

    # Name convention: lowercase, dot-namespaced or hyphenated (e.g. 'plan.ux', 'plan.copy', 'agents-discipline')
    if not re.match(r"^[a-z0-9]+([.-][a-z0-9]+)*(:[a-z0-9]+)*$", name):
        raise ValueError(f"Skill name '{name}' must be lowercase, dot-namespaced, or hyphenated (e.g. 'plan.ux', 'plan.copy', 'agents-discipline').")

    description = data.get("description")
    if not description or not isinstance(description, str) or not description.strip():
        raise ValueError("Frontmatter missing required non-empty string field: 'description'.")

    try:
        metadata = SkillMetadata(
            name=name,
            description=description.strip(),
            version=str(data.get("version", "0.1.0")),
            tags=list(data.get("tags", [])),
            triggers=list(data.get("triggers", [])),
            author=data.get("author", "Patterns at Scale"),
        )
    except ValidationError as exc:
        raise ValueError(f"Skill metadata validation failed: {exc}") from exc

    return Skill(
        metadata=metadata,
        markdown_body=markdown_body.strip(),
        file_path=file_path,
        source_type=source_type,
    )


def validate_skill_file(file_path: Path, source_type: SkillSourceType = SkillSourceType.WORKSPACE) -> Tuple[bool, str, Skill | None]:
    """
    Validate a physical SKILL.md file. Returns (is_valid, message, skill_or_none).
    """
    if not file_path.exists():
        return False, f"File does not exist: {file_path}", None

    try:
        content = file_path.read_text(encoding="utf-8")
        skill = parse_skill_text(content, file_path=file_path, source_type=source_type)
        return True, f"Skill '{skill.name}' is valid.", skill
    except Exception as exc:
        return False, str(exc), None
