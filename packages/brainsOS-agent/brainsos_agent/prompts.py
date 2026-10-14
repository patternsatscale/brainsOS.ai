"""Modular prompt resolution, global injection, and envelope rendering for brainsOS agents."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from .config import get_data_dir, get_settings_dir

logger = logging.getLogger("brainsos_agent.prompts")


def _find_repo_root(start: Path | None = None) -> Path:
    """Discovers the root directory of the repository or appliance installation."""
    if "BRAINSOS_ROOT" in os.environ:
        return Path(os.environ["BRAINSOS_ROOT"]).resolve()

    search_starts = [start] if start else [Path.cwd(), Path(__file__).resolve().parent]
    for cur in search_starts:
        if cur is None:
            continue
        cur = cur.resolve()
        for parent in [cur, *cur.parents]:
            if (
                (parent / "config" / "default_settings").is_dir()
                or (parent / "config" / "default_agents").is_dir()
                or (parent / ".git").exists()
            ):
                return parent

    return Path.cwd().resolve()


def _strip_frontmatter(content: str) -> str:
    """Strips YAML frontmatter from Markdown text if present."""
    text = content.strip()
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return text


def get_prompts_dirs(base_dir: Path | str | None = None) -> list[Path]:
    """Returns candidate directories for prompt templates in priority order.

    Priority:
    1. BRAINSOS_PROMPTS_DIR (if explicitly set)
    2. base_dir / data / settings / prompts (if base_dir is passed)
    3. BRAINSOS_SETTINGS_DIR / prompts
    4. BRAINSOS_DATA_DIR / settings / prompts
    5. repo_root / data / settings / prompts
    6. repo_root / config / default_settings / prompts
    """
    candidates: list[Path] = []
    base = Path(base_dir).resolve() if base_dir else _find_repo_root()

    if "BRAINSOS_PROMPTS_DIR" in os.environ:
        p = Path(os.environ["BRAINSOS_PROMPTS_DIR"])
        candidates.append(p.resolve() if p.is_absolute() else (base / p).resolve())

    if base_dir:
        candidates.append(base / "data" / "settings" / "prompts")
        candidates.append(base / "settings" / "prompts")
        candidates.append(base / "config" / "default_settings" / "prompts")

    # Settings dir candidates
    settings_dir = get_settings_dir()
    candidates.append(settings_dir / "prompts")

    data_dir = get_data_dir()
    candidates.append(data_dir / "settings" / "prompts")

    candidates.append(base / "data" / "settings" / "prompts")
    candidates.append(base / "config" / "default_settings" / "prompts")

    # Deduplicate while preserving order
    seen: set[Path] = set()
    result: list[Path] = []
    for c in candidates:
        res = c.resolve()
        if res not in seen:
            seen.add(res)
            result.append(res)
    return result


def resolve_global_prompts(base_dir: Path | str | None = None) -> list[str]:
    """Resolves and loads all global prompt directives from prompts/global/*.md.

    Files are loaded in alphabetical/numeric order (e.g. 00_manifesto.md, 10_rules.md).
    Returns list of stripped prompt strings.
    """
    for prompts_dir in get_prompts_dirs(base_dir):
        global_dir = prompts_dir / "global"
        if global_dir.is_dir():
            files = sorted(global_dir.glob("*.md"))
            if files:
                prompts: list[str] = []
                for f in files:
                    try:
                        content = f.read_text(encoding="utf-8")
                        body = _strip_frontmatter(content)
                        if body:
                            prompts.append(body)
                    except Exception as e:
                        logger.warning("Failed to read global prompt %s: %s", f, e)
                if prompts:
                    return prompts
    return []


def resolve_channel_prompt(
    channel: str,
    agent_id: str | None = None,
    base_dir: Path | str | None = None,
) -> str:
    """Resolves channel-specific prompt directives (e.g. email.md, signal.md).

    Cascading Fallback:
    1. data/agents/{agent_id}/prompts/channels/{channel}.md (agent custom override)
    2. data/agents/{agent_id}/prompts/{channel}.md
    3. settings/prompts/channels/{channel}.md (fleet-wide live setting)
    4. config/default_settings/prompts/channels/{channel}.md (core default)
    """
    norm_channel = channel.lower().strip()
    if not norm_channel.endswith(".md"):
        filename = f"{norm_channel}.md"
    else:
        filename = norm_channel

    base = Path(base_dir).resolve() if base_dir else _find_repo_root()

    # 1 & 2. Check per-agent override if agent_id is provided
    if agent_id:
        if base_dir:
            agents_dir = base / "data" / "agents"
        else:
            from .config import get_agents_dir

            agents_dir = get_agents_dir()
        agent_candidates = [
            agents_dir / agent_id / "prompts" / "channels" / filename,
            agents_dir / agent_id / "prompts" / filename,
            base / "data" / "agents" / agent_id / "prompts" / "channels" / filename,
            base / "data" / "agents" / agent_id / "prompts" / filename,
        ]
        for cand in agent_candidates:
            if cand.is_file() and cand.stat().st_size > 0:
                try:
                    return _strip_frontmatter(cand.read_text(encoding="utf-8"))
                except Exception as e:
                    logger.warning("Failed to read agent channel prompt %s: %s", cand, e)

    # 3 & 4. Check fleet settings & default settings
    for prompts_dir in get_prompts_dirs(base_dir):
        channel_file = prompts_dir / "channels" / filename
        if channel_file.is_file() and channel_file.stat().st_size > 0:
            try:
                return _strip_frontmatter(channel_file.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning("Failed to read channel prompt %s: %s", channel_file, e)

    return ""


def render_inbound_envelope(
    channel: str,
    metadata: dict[str, Any],
    body: str,
    base_dir: Path | str | None = None,
) -> str:
    """Wraps an incoming user message turn in a structured envelope with channel metadata."""
    norm_channel = channel.lower().strip()
    if not norm_channel.endswith(".md"):
        filename = f"{norm_channel}.md"
    else:
        filename = norm_channel

    template: str | None = None
    for prompts_dir in get_prompts_dirs(base_dir):
        env_file = prompts_dir / "envelopes" / filename
        if env_file.is_file() and env_file.stat().st_size > 0:
            try:
                template = env_file.read_text(encoding="utf-8")
                break
            except Exception as e:
                logger.warning("Failed to read envelope template %s: %s", env_file, e)

    clean_body = body.strip()

    if not template:
        if norm_channel.startswith("email"):
            template = (
                "--- INBOUND EMAIL MESSAGE ---\n"
                "From: {sender}\n"
                "To: {recipient}\n"
                "Subject: {subject}\n"
                "Date: {date_utc}\n"
                "Thread-ID: {thread_id}\n\n"
                "{body}\n"
                "-----------------------------\n"
                "[Email Response Directives: You are replying to the inbound email above. Your text response below will be automatically captured, formatted, and delivered as the email reply to {sender}. Do NOT call `send_email` or other email tools to reply. Format your reply directly using clean semantic HTML (<p>, <h3>, <ul>, <strong>) without markdown code fences.]"
            )
        else:
            return clean_body

    formatted = template
    for key, val in {
        "{sender}": str(metadata.get("sender", "")),
        "{recipient}": str(metadata.get("recipient", "")),
        "{subject}": str(metadata.get("subject", "")),
        "{date_utc}": str(metadata.get("date_utc", "")),
        "{thread_id}": str(metadata.get("thread_id", "")),
        "{body}": clean_body,
    }.items():
        formatted = formatted.replace(key, val)

    return formatted.strip()


def assemble_system_prompt(
    profile: Any,
    resolved_soul: str | None = None,
    channel: str | None = "email",
    base_dir: Path | str | None = None,
) -> str:
    """Assembles the complete layered system prompt for an agent turn.

    Layer 0: Global Directives (prompts/global/*.md, e.g. 00_manifesto.md)
    Layer 1: Agent Persona (SOUL.md)
    Layer 2: OKF Working Memory Rules (memory_root/rules/*.md)
    Layer 3: Runtime Environment & Tool Guidelines
    Layer 4: Channel Communication Directives (prompts/channels/<channel>.md)
    """
    parts: list[str] = []

    # 1. Global prompt directives (e.g. 00_manifesto.md)
    global_prompts = resolve_global_prompts(base_dir=base_dir)
    for gp in global_prompts:
        if gp:
            parts.append(gp)

    # 2. Base Persona from SOUL.md / SoulResolver
    persona_text = (resolved_soul or "").strip()
    if not persona_text and getattr(profile, "soul", None):
        from .souls import resolve_soul

        try:
            persona_text = resolve_soul(profile.soul, base_dir=base_dir)
        except Exception:
            persona_text = ""
    if not persona_text and getattr(profile, "soul_path", None) and profile.soul_path.exists():
        try:
            persona_text = profile.soul_path.read_text(encoding="utf-8").strip()
        except Exception as e:
            logger.warning("Failed to read SOUL.md at %s: %s", profile.soul_path, e)
    if not persona_text:
        persona_text = f"You are {getattr(profile, 'name', 'Agent')}, an autonomous AI agent in the brainsOS fleet."
    parts.append(persona_text)

    # 3. Inject OKF working memory rules / guidelines from memory_root/rules
    memory_root = getattr(profile, "memory_root", None)
    if memory_root and Path(memory_root).exists():
        rules_dir = Path(memory_root) / "rules"
        if rules_dir.exists() and rules_dir.is_dir():
            for rule_file in sorted(rules_dir.glob("*.md")):
                try:
                    rule_text = rule_file.read_text(encoding="utf-8").strip()
                    rule_body = _strip_frontmatter(rule_text)
                    if rule_body:
                        parts.append(f"\n### Memory Guideline ({rule_file.stem})\n{rule_body}")
                except Exception as e:
                    logger.debug("Could not read rule file %s: %s", rule_file, e)

    agent_id = getattr(profile, "id", None) or getattr(profile, "name", "agent")
    email_addr = getattr(profile, "email", "agent@brainsos.local")
    name = getattr(profile, "name", "Agent")
    # 4. Runtime environment & memory partition isolation guidelines (Rule 7 compliant)
    parts.append(
        f"\n### Runtime Environment & Memory Guidelines\n"
        f"- Assigned Identity: {name} <{email_addr}>\n"
        f"- Workspace Root: /workspace (or /data/agents/{agent_id}/workspace)\n"
        f"- Memory Partition: /data/agents/{agent_id}/memories\n"
        f"- Memory Tools: To store long-term notes, research summaries, facts, and rules, invoke `write_memory(rel_path, content)` (e.g. `write_memory('research/topic.md', content='...')`). Your memory operations are automatically and transparently scoped to your assigned memory partition.\n"
    )

    # 5. Channel-specific prompt directives (e.g. email.md)
    if channel:
        channel_prompt = resolve_channel_prompt(channel, agent_id=agent_id, base_dir=base_dir)
        if channel_prompt:
            parts.append(f"\n{channel_prompt}")

    return "\n\n".join(parts)
