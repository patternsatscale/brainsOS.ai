"""OKF Markdown Thread History Reconstruction and Context Assembly for brainsOS agents."""

from __future__ import annotations

import datetime
import json
import re
from pathlib import Path

from brainsos_mail.models import ParsedInboundEmail

from brainsos_agent.models import AgentProfile
from brainsos_agent.souls import resolve_soul  # noqa: F401


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
        """Parses structured JSONL dialog turns from the thread's OKF markdown file."""
        file_path = cls.get_thread_file_path(memory_root, thread_id)
        if not file_path.exists():
            return []

        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception:
            return []

        lines = content.split("\n")
        start_idx = 0
        if lines and lines[0].strip() == "---":
            for i in range(1, len(lines)):
                if lines[i].strip() == "---":
                    start_idx = i + 1
                    break

        turns: list[dict[str, str]] = []
        for raw_line in lines[start_idx:]:
            line = raw_line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                record = json.loads(line)
            except Exception:
                continue
            if not isinstance(record, dict):
                continue
            role = str(record.get("role", "")).strip().lower()
            text = record.get("content")
            if role in {"user", "assistant", "system", "tool"} and isinstance(text, str) and text.strip():
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
        """Appends a structured JSONL dialogue turn to the thread's OKF .md file."""
        file_path = cls.get_thread_file_path(memory_root, thread_id)
        timestamp_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        clean_text = content.strip()
        if not file_path.exists():
            # Initialize with OKF YAML frontmatter (JSON-escaped metadata prevents newline/YAML injection)
            frontmatter = (
                "---\n"
                f"thread_id: {json.dumps(thread_id, ensure_ascii=True)}\n"
                f"subject: {json.dumps(subject, ensure_ascii=True)}\n"
                f'created_at: "{timestamp_str}"\n'
                'type: "thread-dialogue"\n'
                'format: "okf-jsonl-v1"\n'
                "---\n\n"
            )
            file_path.write_text(frontmatter, encoding="utf-8")

        existing = cls.load_thread_turns(memory_root, thread_id)
        turn_number = len(existing) + 1

        record = {
            "turn": turn_number,
            "role": role,
            "author": author,
            "timestamp": timestamp_str,
            "content": clean_text,
        }
        entry = json.dumps(record, ensure_ascii=True) + "\n"
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

        # 1. System Prompt (Global Directives + Soul / Persona + Working Memory + Channel Directives)
        from brainsos_agent.prompts import assemble_system_prompt

        system_prompt = assemble_system_prompt(profile, channel="email")
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
