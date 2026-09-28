"""brainsOS Lightweight Mail Package."""

from .calendar import generate_ics_event, write_ics_file
from .client import BrainsOSMailClient

__all__ = ["BrainsOSMailClient", "generate_ics_event", "write_ics_file"]
__version__ = "0.1.0"
