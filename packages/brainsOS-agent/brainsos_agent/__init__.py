"""brainsOS-agent: Decoupled autonomous agent runtime SPI and context assembly."""

from .context import ContextAssembler, sanitize_thread_filename
from .models import AgentProfile, OutboundEmail
from .runtime import AgentRuntime
from .souls import SoulNotFoundError, get_soul_path, normalize_soul_name, resolve_soul

__all__ = [
    "AgentProfile",
    "AgentRuntime",
    "ContextAssembler",
    "OutboundEmail",
    "SoulNotFoundError",
    "get_soul_path",
    "normalize_soul_name",
    "resolve_soul",
    "sanitize_thread_filename",
]
__version__ = "0.1.0"
