"""OKF Markdown Thread History Reconstruction and Context Assembly for brainsOS agents."""

from __future__ import annotations

import datetime
import re
from pathlib import Path
from typing import Any

from brainsos_mail.models import ParsedInboundEmail
from brainsos_agent.models import AgentProfile


def sanitize_thread_filename(thread_id: str) -> str:
    """Sanitizes an RFC Message-ID for safe local markdown filesystem storage."""
    clean = thread_id.strip().strip("<>").strip()
    clean = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", clean)
    return f"{clean}.md"


class ContextAssembler:
    """Reconstructs conversation context from human-auditable OKF markdown memory files."""

    @staticmethod
    def get_thread_file_path(memory_root: Path, thread_id: str) -> Path:
        """Resolves the canonical OKF thread file path under memory root."""
        # Enforce Rule 1: Purity guardrail (must be .md markdown)
        filename = sanitize_thread_filename(thread_id)
        if not filename.endswith(".md"):
            raise ValueError(f"Rule 1 Invariant: Memory turns must be stored in .md files, got {filename}")

        threads_dir = Path(memory_root) / "threads"
        threads_dir.mkdir(parents=True, exist_ok=True)
        return threads_dir / filename

    @classmethod
    def load_thread_turns(cls, memory_root: Path, thread_id: str) -> list[dict[str, str]]:
        """Parses stored dialog turns from the thread's OKF markdown file."""
        file_path = cls.get_thread_file_path(memory_root, thread_id)
        if not file_path.exists():
            return []

        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception:
            return []

        # Strip frontmatter if present
        if content.startswith("---"):
            parts = content.split("---", 2)
            body = parts[2] if len(parts) >= 3 else content
        else:
            body = content

        turns: list[dict[str, str]] = []
        # Pattern matching: "## Turn <N>: <role> (<author>) - <timestamp>" or "## <role>:"
        turn_pattern = re.compile(
            r"##\s+(?:Turn\s+\d+:\s+)?(user|assistant|system)(?:\s*\([^)]*\))?(?:\s*-\s*[^\n]+)?\n(.*?)(?=(?:\n##\s+)|$)",
            re.DOTALL | re.IGNORECASE,
        )

        for match in turn_pattern.finditer(body):
            role = match.group(1).lower()
            text = match.group(2).strip()
            if text:
                turns.append({"role": role, "content": text})

        return turns

    @classmethod
    def record_turn(
        cls,
        memory_root: Path,
        thread_id: str,
        subject: str,
        role: str,
        author: str,
        content: str,
    ) -> Path:
        """Appends a dialogue turn to the thread's human-auditable OKF markdown file."""
        file_path = cls.get_thread_file_path(memory_root, thread_id)
        timestamp_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        clean_text = content.strip()
        if not file_path.exists():
            # Initialize with OKF YAML frontmatter
            frontmatter = (
                f"---\n"
                f"thread_id: \"{thread_id}\"\n"
                f"subject: \"{subject}\"\n"
                f"created_at: \"{timestamp_str}\"\n"
                f"type: \"thread-dialogue\"\n"
                f"---\n\n"
                f"# Thread: {subject}\n\n"
            )
            file_path.write_text(frontmatter, encoding="utf-8")

        # Determine turn count
        existing = cls.load_thread_turns(memory_root, thread_id)
        turn_number = len(existing) + 1

        entry = (
            f"\n## Turn {turn_number}: {role} ({author}) - {timestamp_str}\n\n"
            f"{clean_text}\n"
        )
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(entry)

        return file_path

    @classmethod
    def assemble_messages(
        cls,
        email: ParsedInboundEmail,
        profile: AgentProfile,
        include_new_message: bool = True,
        record_inbound: bool = True,
    ) -> list[dict[str, str]]:
        """Assembles the system persona, historical OKF dialog turns, and latest inbound email."""
        messages: list[dict[str, str]] = []

        # 1. System Prompt (Soul / Persona)
        system_prompt = ""
        if profile.soul_path and profile.soul_path.exists():
            try:
                system_prompt = profile.soul_path.read_text(encoding="utf-8").strip()
            except Exception:
                system_prompt = f"You are {profile.name}, an autonomous AI agent in the brainsOS fleet."
        else:
            system_prompt = f"You are {profile.name}, an autonomous AI agent in the brainsOS fleet."

        messages.append({"role": "system", "content": system_prompt})

        # 2. Historical Dialogue Turns from pure OKF memory
        historical_turns = cls.load_thread_turns(profile.memory_root, email.thread_id)
        messages.extend(historical_turns)

        # 3. Append current inbound turn if requested
        if include_new_message and email.clean_body:
            # Check if this turn is already the last turn in history
            if not historical_turns or historical_turns[-1].get("content") != email.clean_body:
                messages.append({"role": "user", "content": email.clean_body})
                if record_inbound:
                    cls.record_turn(
                        memory_root=profile.memory_root,
                        thread_id=email.thread_id,
                        subject=email.subject,
                        role="user",
                        author=email.sender,
                        content=email.clean_body,
                    )

        return messages
