"""brainsOS Lightweight Mail Package."""

from .calendar import generate_ics_event, write_ics_file
from .client import BrainsOSMailClient
from .models import Attachment, ParsedInboundEmail
from .parser import clean_email_body, extract_message_ids, parse_inbound_mime, resolve_thread_id

__all__ = [
    "Attachment",
    "BrainsOSMailClient",
    "ParsedInboundEmail",
    "clean_email_body",
    "extract_message_ids",
    "generate_ics_event",
    "parse_inbound_mime",
    "resolve_thread_id",
    "write_ics_file",
]
__version__ = "0.1.0"

