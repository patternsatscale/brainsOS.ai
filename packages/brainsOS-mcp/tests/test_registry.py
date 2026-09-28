"""Unit tests for brainsos_mcp capability discovery and registration."""

from __future__ import annotations

from brainsos_mcp.registry import MODULE_PROVIDERS, discover_and_register_capabilities
from mcp.server.fastmcp import FastMCP


def test_discover_and_register_capabilities():
    """Verify that all core domains are discovered and registered onto FastMCP."""
    mcp = FastMCP("test-server")
    registered = discover_and_register_capabilities(mcp)

    assert "memory" in registered
    assert "queue" in registered
    assert "mail" in registered
    assert "telemetry" in registered

    assert "read_memory" in registered["memory"]
    assert "write_memory" in registered["memory"]
    assert "enqueue_task" in registered["queue"]
    assert "get_task_status" in registered["queue"]
    assert "send_email" in registered["mail"]
    assert "read_email" in registered["mail"]
    assert "get_energy_metrics" in registered["telemetry"]
    assert "emit_telemetry_event" in registered["telemetry"]


def test_registry_graceful_on_missing_module(monkeypatch):
    """Verify registry gracefully handles optional missing dependencies."""
    mcp = FastMCP("test-fallback")
    monkeypatch.setattr(
        "brainsos_mcp.registry.MODULE_PROVIDERS",
        MODULE_PROVIDERS + [("nonexistent", "brainsos_mcp.modules.fake", "register_fake")],
    )
    registered = discover_and_register_capabilities(mcp)
    assert "nonexistent" not in registered
    assert "memory" in registered
