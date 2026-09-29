"""Data models for agent profiles and execution payloads."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Any
import yaml
from pydantic import AfterValidator, BaseModel, Field


def _validate_email(v: str) -> str:
    cleaned = str(v).strip()
    if not re.match(r"^[^@\s]+@[^@\s]+(?:\.[^@\s]+)+$", cleaned):
        raise ValueError(f"Invalid email address: '{v}'")
    return cleaned.lower()


# RFC 5322 compatible email type supporting internal .local and private appliance domains
EmailStr = Annotated[str, AfterValidator(_validate_email)]


class AgentProfile(BaseModel):
    """Dynamic profile for an autonomous agent defined in config/agents.yaml."""

    name: str
    email: EmailStr
    id: str | None = None
    runtime: str = "hermes"
    model: str = "brainsos-core"
    soul_path: Path
    memory_root: Path
    workspace_root: Path
    mcp_modules: list[str] = Field(default_factory=list)

    @classmethod
    def from_agent_dict(cls, data: dict[str, Any], base_path: Path | str = ".") -> AgentProfile:
        base = Path(base_path)
        agent_id = str(data.get("id", ""))
        name = str(data.get("name", agent_id))

        # Email address extraction
        comms = data.get("comms", {}) if isinstance(data.get("comms"), dict) else {}
        email_info = comms.get("email", {}) if isinstance(comms.get("email"), dict) else {}
        email_addr = (
            data.get("email")
            or email_info.get("address")
            or (f"{agent_id}@brainsos.local" if agent_id else "agent@brainsos.local")
        )

        runtime = str(data.get("runtime", "hermes"))

        # Model extraction
        models = data.get("models", {}) if isinstance(data.get("models"), dict) else {}
        model = str(
            data.get("model")
            or models.get("default")
            or "brainsos-core"
        )

        persona_str = data.get("persona") or data.get("soul_path") or f"config/hermes/{agent_id}/SOUL.md"
        memory_str = (
            data.get("memory_root")
            or (data.get("memory", {}).get("path") if isinstance(data.get("memory"), dict) else None)
            or f"./data/agent_memories/{agent_id}"
        )
        workspace_str = (
            data.get("workspace_root")
            or (data.get("workspace", {}).get("path") if isinstance(data.get("workspace"), dict) else None)
            or f"./data/agent_workspaces/{agent_id}"
        )

        soul_path = Path(persona_str) if Path(persona_str).is_absolute() else base / persona_str
        memory_root = Path(memory_str) if Path(memory_str).is_absolute() else base / memory_str
        workspace_root = Path(workspace_str) if Path(workspace_str).is_absolute() else base / workspace_str

        mcp_modules = data.get("mcp_modules") or data.get("mcp", [])
        if not isinstance(mcp_modules, list):
            mcp_modules = []

        return cls(
            name=name,
            id=agent_id,
            email=email_addr,
            runtime=runtime,
            model=model,
            soul_path=soul_path,
            memory_root=memory_root,
            workspace_root=workspace_root,
            mcp_modules=mcp_modules,
        )

    @classmethod
    def from_manifest_yaml(
        cls,
        manifest_source: str | Path,
        agent_id: str | None = None,
        base_path: Path | str | None = None,
    ) -> list[AgentProfile] | AgentProfile:
        """Parse agent profiles directly from a YAML file or string."""
        if isinstance(manifest_source, Path) or (
            isinstance(manifest_source, str) and "\n" not in manifest_source and Path(manifest_source).exists()
        ):
            p = Path(manifest_source)
            with open(p, "r", encoding="utf-8") as f:
                doc = yaml.safe_load(f)
            base = base_path or p.parent.resolve()
        else:
            doc = yaml.safe_load(str(manifest_source))
            base = base_path or Path(".").resolve()

        agents_list = doc.get("agents", []) if isinstance(doc, dict) else []
        profiles = [cls.from_agent_dict(a, base_path=base) for a in agents_list if isinstance(a, dict)]

        if agent_id:
            for p in profiles:
                if p.id == agent_id or p.name == agent_id or p.email.startswith(f"{agent_id}@"):
                    return p
            raise ValueError(f"Agent with id '{agent_id}' not found in manifest")
        return profiles


class OutboundEmail(BaseModel):
    """Normalized response email produced by an agent runtime."""

    to: str
    subject: str
    body: str
    thread_id: str
    in_reply_to: str | None = None
    references: str | None = None
    attachments: list[Any] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
