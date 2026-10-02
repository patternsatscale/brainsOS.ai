"""brainsos_mcp.server — FastMCP server instantiation and entry point."""

from __future__ import annotations

import logging
import sys

from mcp.server.fastmcp import FastMCP

from brainsos_mcp.registry import discover_and_register_capabilities

logger = logging.getLogger("brainsos_mcp")


def create_server() -> FastMCP:
    """Instantiate and configure the brainsOS FastMCP server."""
    mcp = FastMCP(
        "brainsos",
        instructions=(
            "brainsOS universal agent capabilities server. "
            "Provides decoupled access to memory, asynchronous work queue, email, and energy telemetry."
        ),
    )
    discover_and_register_capabilities(mcp)
    return mcp


mcp_server = create_server()


def main() -> None:
    """CLI and module execution entry point (runs stdio transport by default)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )
    logger.info("Starting brainsOS MCP server over stdio...")
    mcp_server.run()


if __name__ == "__main__":
    main()
