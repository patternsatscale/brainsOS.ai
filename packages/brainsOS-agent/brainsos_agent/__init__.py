"""brainsOS-agent: Decoupled autonomous agent runtime SPI and context assembly."""

from .config import (
    get_agent_apps_dir,
    get_comms_dir,
    get_control_plane_dir,
    get_data_dir,
    get_memories_dir,
    get_runners_dir,
    get_settings_dir,
    get_souls_dir,
    get_workspaces_dir,
)
from .context import ContextAssembler, sanitize_thread_filename
from .models import AgentProfile, OutboundEmail
from .runtime import AgentRuntime
from .souls import SoulNotFoundError, get_soul_path, normalize_soul_name, resolve_soul
from .worker import SingleInstanceLock

__all__ = [
    "AgentProfile",
    "AgentRuntime",
    "ContextAssembler",
    "OutboundEmail",
    "SingleInstanceLock",
    "SoulNotFoundError",
    "get_agent_apps_dir",
    "get_comms_dir",
    "get_control_plane_dir",
    "get_data_dir",
    "get_memories_dir",
    "get_runners_dir",
    "get_settings_dir",
    "get_soul_path",
    "get_souls_dir",
    "get_workspaces_dir",
    "normalize_soul_name",
    "resolve_soul",
    "sanitize_thread_filename",
]

__version__ = "0.1.0"
