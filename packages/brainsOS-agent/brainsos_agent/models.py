"""Data models for agent profiles and execution payloads."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Any

import yaml
from pydantic import AfterValidator, BaseModel, Field

from .config import (
    get_data_dir,
    get_memories_dir,
    get_runners_dir,
    get_settings_dir,
    get_souls_dir,
    get_workspaces_dir,
)
from .souls import SoulNotFoundError, get_soul_path


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
    soul: str | None = None
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

        runtime = str(data.get("runtime") or data.get("runner") or "hermes")

        # Model extraction
        models = data.get("models", {}) if isinstance(data.get("models"), dict) else {}
        model = str(data.get("model") or models.get("default") or "brainsos-core")

        soul_name = data.get("soul") or (agent_id if agent_id else None)
        soul_path: Path | None = None

        # Direct soul_path override (e.g. from tests)
        if "soul_path" in data and isinstance(data["soul_path"], Path):
            soul_path = data["soul_path"]
            if not soul_name:
                soul_name = soul_path.stem

        if soul_path is None and soul_name:
            try:
                soul_path = get_soul_path(soul_name, base_dir=base)
            except SoulNotFoundError:
                soul_path = None

        if soul_path is None:
            persona_str = (
                data.get("persona")
                or (str(data.get("soul_path")) if data.get("soul_path") else None)
                or f"config/default_runners/hermes/{agent_id}/SOUL.md"
            )
            persona_path = base / persona_str
            if not persona_path.exists():
                for candidate in [
                    base / "config" / "default_souls" / f"{agent_id}.md",
                    get_souls_dir() / f"{agent_id}.md",
                    base / "data" / "souls" / f"{agent_id}.md",
                    get_runners_dir() / "hermes" / agent_id / "SOUL.md",
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
            soul_path = Path(persona_str) if Path(persona_str).is_absolute() else persona_path

        default_memory = get_memories_dir() / agent_id
        default_workspace = get_workspaces_dir() / agent_id

        def _resolve_scoped_path(path_val: Any, default_path: Path, namespace: str) -> Path:
            if not path_val:
                return default_path
            path_str = str(path_val)
            p = Path(path_str)
            if p.is_absolute():
                return p.resolve()

            norm = path_str.replace("\\", "/")
            if norm.startswith("./"):
                norm = norm[2:]
            if norm.startswith("data/"):
                norm = norm[5:]

            if norm.startswith(f"{namespace}/"):
                sub = norm[len(namespace) + 1 :]
                target_dir = get_memories_dir() if namespace == "agent_memories" else get_workspaces_dir()
                return (target_dir / sub).resolve()

            return (base / norm).resolve()

        memory_raw = (
            data.get("memory_root")
            or (data.get("memory", {}).get("path") if isinstance(data.get("memory"), dict) else None)
        )
        workspace_raw = (
            data.get("workspace_root")
            or (data.get("workspace", {}).get("path") if isinstance(data.get("workspace"), dict) else None)
        )

        memory_root = _resolve_scoped_path(memory_raw, default_memory, "agent_memories")
        workspace_root = _resolve_scoped_path(workspace_raw, default_workspace, "agent_workspaces")

        mcp_modules = data.get("mcp_modules") or data.get("mcp", [])
        if not isinstance(mcp_modules, list):
            mcp_modules = []

        return cls(
            name=name,
            id=agent_id,
            soul=str(soul_name) if soul_name else None,
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
        if isinstance(manifest_source, Path) or (isinstance(manifest_source, str) and "\n" not in manifest_source):
            p = Path(manifest_source)
            if not p.exists():
                if p.name in ("agents.yaml", "default_agents.yaml"):
                    for cand in [
                        get_settings_dir() / "agents.yaml",
                        get_data_dir() / "settings" / "agents.yaml",
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
            elif p.parent.name == "settings":
                base = p.parent.parent.resolve()
            else:
                base = p.parent.resolve()
        else:
            doc = yaml.safe_load(str(manifest_source))
            base = Path(base_path).resolve() if base_path else Path(".").resolve()

        agents_raw = doc.get("agents", []) if isinstance(doc, dict) else []
        if isinstance(agents_raw, dict):
            agents_list = []
            for k, v in agents_raw.items():
                if isinstance(v, dict):
                    entry = {"id": k, **v}
                    if "soul" not in entry:
                        entry["soul"] = k
                    agents_list.append(entry)
        elif isinstance(agents_raw, list):
            agents_list = [a for a in agents_raw if isinstance(a, dict)]
        else:
            agents_list = []

        profiles = [cls.from_agent_dict(a, base_path=base) for a in agents_list if isinstance(a, dict)]

        if agent_id:
            for prof in profiles:
                if prof.id == agent_id or prof.name == agent_id or prof.email.startswith(f"{agent_id}@"):
                    return prof
            raise ValueError(f"Agent with id '{agent_id}' not found in manifest")
        return profiles

    from_dict = from_agent_dict


class OutboundEmail(BaseModel):
    """Normalized response email produced by an agent runtime."""

    to: str
    subject: str
    body: str
    thread_id: str
    in_reply_to: str | None = None
    references: str | None = None
    html_body: str | None = None
    attachments: list[Any] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
