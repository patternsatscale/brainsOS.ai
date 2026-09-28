"""Unit tests for brainsos_mail RFC 5545 calendar ICS generation."""

import datetime
import tempfile
import unittest
from pathlib import Path

from brainsos_mail.calendar import generate_ics_event, write_ics_file


class TestCalendar(unittest.TestCase):
    def test_generate_ics_event_basic(self):
        start = 1727280000.0  # Unix timestamp
        end = 1727283600.0    # +1 hour

        ics = generate_ics_event(
            summary="Test Workload Task",
            start_time=start,
            end_time=end,
            description="Completed automated code generation",
            uid="task-12345@brainsos.local",
            organizer="terrastella@brainsos.local",
            attendee="operator@brainsos.local",
            status="CONFIRMED",
        )

        self.assertIn("BEGIN:VCALENDAR", ics)
        self.assertIn("BEGIN:VEVENT", ics)
        self.assertIn("VERSION:2.0", ics)
        self.assertIn("UID:task-12345@brainsos.local", ics)
        self.assertIn("SUMMARY:Test Workload Task", ics)
        self.assertIn("DESCRIPTION:Completed automated code generation", ics)
        self.assertIn("ORGANIZER;CN=terrastella@brainsos.local:mailto:terrastella@brainsos.local", ics)
        self.assertIn("ATTENDEE;CN=operator@brainsos.local:mailto:operator@brainsos.local", ics)
        self.assertIn("STATUS:CONFIRMED", ics)
        self.assertIn("END:VEVENT", ics)
        self.assertIn("END:VCALENDAR", ics)

    def test_generate_ics_event_with_datetime(self):
        start = datetime.datetime(2026, 9, 25, 12, 0, 0, tzinfo=datetime.timezone.utc)
        ics = generate_ics_event(
            summary="Datetime Task",
            start_time=start,
            description="Line 1\nLine 2, with comma and; semicolon",
        )

        self.assertIn("DTSTART:20260925T120000Z", ics)
        self.assertIn("DTEND:20260925T121500Z", ics)  # Default +15 mins
        self.assertIn("Line 1\\nLine 2\\, with comma and\\; semicolon", ics)

    def test_write_ics_file_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "workspace" / "calendar" / "task1.ics"
            ics_content = generate_ics_event(summary="Save Test", start_time=1727280000.0)

            written_path = write_ics_file(dest, ics_content)
            self.assertTrue(written_path.exists())
            content = written_path.read_text(encoding="utf-8")
            self.assertIn("BEGIN:VCALENDAR", content)

    def test_write_ics_file_rule1_purity_guard(self):
        ics_content = generate_ics_event(summary="Forbidden Test", start_time=1727280000.0)

        with self.assertRaises(ValueError) as ctx:
            write_ics_file("/data/agent_memories/terrastella/events.ics", ics_content)
        self.assertIn("Rule 1 Invariant Violation", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            write_ics_file("/memories/calendar.ics", ics_content)
        self.assertIn("Rule 1 Invariant Violation", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

