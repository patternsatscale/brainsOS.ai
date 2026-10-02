"""brainsos_mcp.registry — Dynamic Capability Discovery and Tool Registration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("brainsos_mcp")

# Built-in capability providers
MODULE_PROVIDERS: list[tuple[str, str, str]] = [
    ("memory", "brainsos_mcp.modules.memory", "register_memory_tools"),
    ("queue", "brainsos_mcp.modules.queue", "register_queue_tools"),
    ("mail", "brainsos_mcp.modules.mail", "register_mail_tools"),
    ("telemetry", "brainsos_mcp.modules.telemetry", "register_telemetry_tools"),
]


def discover_and_register_capabilities(mcp: FastMCP) -> dict[str, list[str]]:
    """Dynamically discover, load, and register capabilities across available brainsOS packages."""
    registered: dict[str, list[str]] = {}

    for domain, module_path, func_name in MODULE_PROVIDERS:
        try:
            mod = __import__(module_path, fromlist=[func_name])
            func: Callable[[FastMCP], list[str]] = getattr(mod, func_name)
            tool_names = func(mcp)
            registered[domain] = tool_names
            logger.info("Successfully loaded %s capabilities (%d tools): %s", domain, len(tool_names), tool_names)
        except ImportError as e:
            logger.warning("Optional capability domain '%s' not available (missing dependency): %s", domain, e)
        except Exception as e:
            logger.error("Failed to register capability domain '%s': %s", domain, e, exc_info=True)

    return registered
