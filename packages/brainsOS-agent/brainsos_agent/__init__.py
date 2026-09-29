"""brainsOS-agent: Decoupled autonomous agent runtime SPI and context assembly."""

from .context import ContextAssembler, sanitize_thread_filename
from .models import AgentProfile, OutboundEmail
from .runtime import AgentRuntime

__all__ = [
    "AgentProfile",
    "AgentRuntime",
    "ContextAssembler",
    "OutboundEmail",
    "sanitize_thread_filename",
]
__version__ = "0.1.0"
