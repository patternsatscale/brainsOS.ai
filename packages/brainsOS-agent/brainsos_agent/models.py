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
        raw_email = data.get("email")
        comms = data.get("comms", {}) if isinstance(data.get("comms"), dict) else {}
        email_info = comms.get("email", {}) if isinstance(comms.get("email"), dict) else {}

        if isinstance(raw_email, str):
            email_addr = raw_email
        elif isinstance(raw_email, dict):
            email_addr = raw_email.get("address") or f"{agent_id}@brainsos.local"
        elif email_info.get("address"):
            email_addr = str(email_info.get("address"))
        else:
            email_addr = f"{agent_id}@brainsos.local" if agent_id else "agent@brainsos.local"

        runtime = str(data.get("runtime", "hermes"))

        # Model extraction
        models = data.get("models", {}) if isinstance(data.get("models"), dict) else {}
        model = str(
            data.get("model")
            or models.get("default")
            or "brainsos-core"
        )

        persona_str = (
            data.get("persona")
            or data.get("soul_path")
            or f"config/default_runners/hermes/{agent_id}/SOUL.md"
        )
        persona_path = base / persona_str
        if not persona_path.exists():
            for candidate in [
                base / "data" / "runners" / "hermes" / agent_id / "SOUL.md",
                base / "config" / "default_runners" / "hermes" / agent_id / "SOUL.md",
                base / "data" / "runners" / f"{agent_id}-sdk" / agent_id / "SOUL.md",
                base / "config" / "default_runners" / f"{agent_id}-sdk" / agent_id / "SOUL.md",
                base / "data" / "runners" / agent_id / "SOUL.md",
                base / "config" / "default_runners" / agent_id / "SOUL.md",
                base / "config" / "hermes" / agent_id / "SOUL.md",
            ]:
                if candidate.exists():
                    persona_path = candidate
                    break
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

        soul_path = Path(persona_str) if Path(persona_str).is_absolute() else persona_path
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
            isinstance(manifest_source, str) and "\n" not in manifest_source
        ):
            p = Path(manifest_source)
            if not p.exists():
                if p.name in ("agents.yaml", "default_agents.yaml"):
                    for cand in [
                        Path("data/settings/agents.yaml"),
                        Path("config/default_settings/agents.yaml"),
                        Path("config/agents.yaml"),
                    ]:
                        if cand.exists():
                            p = cand
                            break

            if not p.exists():
                raise FileNotFoundError(f"Manifest file not found: {manifest_source}")

            with open(p, "r", encoding="utf-8") as f:
                doc = yaml.safe_load(f)
            if base_path:
                base = Path(base_path).resolve()
            elif p.parent.name == "config":
                base = p.parent.parent.resolve()
            elif p.parent.name in ("default_settings", "settings") and p.parent.parent.name in ("config", "data"):
                base = p.parent.parent.parent.resolve()
            else:
                base = p.parent.resolve()
        else:
            doc = yaml.safe_load(str(manifest_source))
            base = Path(base_path).resolve() if base_path else Path(".").resolve()

        agents_list = doc.get("agents", []) if isinstance(doc, dict) else []
        profiles = [cls.from_agent_dict(a, base_path=base) for a in agents_list if isinstance(a, dict)]

        if agent_id:
            for prof in profiles:
                if prof.id == agent_id or prof.name == agent_id or prof.email.startswith(f"{agent_id}@"):
                    return prof
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
