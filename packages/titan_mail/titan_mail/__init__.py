"""Project Titan Lightweight Mail Package."""

from .client import TitanMailClient
from .calendar import generate_ics_event, write_ics_file

__all__ = ["TitanMailClient", "generate_ics_event", "write_ics_file"]
__version__ = "0.1.0"
