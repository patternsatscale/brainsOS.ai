"""Project Titan: RFC 5545 Calendar (ICS) Event Generation & Export.

Enables autonomous agents to record workload execution events into iCalendar (.ics)
format for calendar synchronization and tracking.
"""

from __future__ import annotations

import datetime
from pathlib import Path
import time
from typing import Optional, Union
import uuid


def _format_dt(dt_val: Union[datetime.datetime, float, int]) -> str:
    """Format datetime or unix timestamp into RFC 5545 UTC timestamp (YYYYMMDDTHHMMSSZ)."""
    if isinstance(dt_val, (int, float)):
        dt = datetime.datetime.fromtimestamp(dt_val, tz=datetime.timezone.utc)
    elif isinstance(dt_val, datetime.datetime):
        if dt_val.tzinfo is None:
            dt = dt_val.replace(tzinfo=datetime.timezone.utc)
        else:
            dt = dt_val.astimezone(datetime.timezone.utc)
    else:
        raise TypeError(f"Expected datetime or timestamp, got {type(dt_val)}")

    return dt.strftime("%Y%m%dT%H%M%SZ")


def _escape_ics_text(text: str) -> str:
    """Escape special characters in text according to RFC 5545."""
    if not text:
        return ""
    text = text.replace("\\", "\\\\")
    text = text.replace(";", "\\;")
    text = text.replace(",", "\\,")
    text = text.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")
    return text


def generate_ics_event(
    summary: str,
    start_time: Union[datetime.datetime, float, int],
    end_time: Optional[Union[datetime.datetime, float, int]] = None,
    description: Optional[str] = None,
    uid: Optional[str] = None,
    organizer: Optional[str] = None,
    attendee: Optional[str] = None,
    status: str = "CONFIRMED",
) -> str:
    """Generate an RFC 5545 compliant VCALENDAR string containing a single VEVENT.

    Args:
        summary: Event title / summary (e.g. "[Workload] Process Email Directive")
        start_time: Start timestamp or datetime
        end_time: End timestamp or datetime (defaults to start_time + 15 mins if omitted)
        description: Detailed task log / workload description
        uid: Globally unique identifier (defaults to uuid4 string)
        organizer: Organizer email / identity
        attendee: Attendee email / identity
        status: Event status (CONFIRMED, TENTATIVE, CANCELLED)

    Returns:
        RFC 5545 formatted .ics calendar string.
    """
    if end_time is None:
        if isinstance(start_time, (int, float)):
            end_time = start_time + 900.0  # 15 minutes default
        elif isinstance(start_time, datetime.datetime):
            end_time = start_time + datetime.timedelta(minutes=15)

    event_uid = uid or f"{uuid.uuid4()}@titan.local"
    dtstamp_str = _format_dt(time.time())
    dtstart_str = _format_dt(start_time)
    dtend_str = _format_dt(end_time)

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Project Titan//Agent Calendar Subsystem//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{event_uid}",
        f"DTSTAMP:{dtstamp_str}",
        f"DTSTART:{dtstart_str}",
        f"DTEND:{dtend_str}",
        f"SUMMARY:{_escape_ics_text(summary)}",
    ]

    if description:
        lines.append(f"DESCRIPTION:{_escape_ics_text(description)}")

    if organizer:
        clean_org = organizer.replace("mailto:", "").strip()
        lines.append(f"ORGANIZER;CN={_escape_ics_text(clean_org)}:mailto:{clean_org}")

    if attendee:
        clean_att = attendee.replace("mailto:", "").strip()
        lines.append(f"ATTENDEE;CN={_escape_ics_text(clean_att)}:mailto:{clean_att}")

    lines.append(f"STATUS:{status.upper()}")
    lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    lines.append("")  # Trailing newline

    return "\r\n".join(lines)


def write_ics_file(file_path: Union[str, Path], ics_content: str) -> Path:
    """Persist an ICS calendar file to disk, enforcing Rule 1 Memory Plane Purity.

    Args:
        file_path: Destination path for .ics file
        ics_content: Formatted RFC 5545 calendar string

    Returns:
        Resolved Path object of the written file.
    """
    path = Path(file_path).resolve()
    path_str = str(path)

    # Rule 1 Memory Plane Purity Guard
    if "/memories" in path_str or "agent_memories" in path_str:
        raise ValueError(
            f"Rule 1 Invariant Violation: Calendar .ics path '{file_path}' resides within /memories. "
            "Calendar files must reside in container workspace (/workspace/calendar) or host data paths."
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(ics_content)

    return path
