"""brainsOS Lightweight Mail Package."""

from .client import BrainsOSMailClient
from .calendar import generate_ics_event, write_ics_file

__all__ = ["BrainsOSMailClient", "generate_ics_event", "write_ics_file"]
__version__ = "0.1.0"
