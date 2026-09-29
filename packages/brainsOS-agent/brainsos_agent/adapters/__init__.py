"""Adapter implementations connecting brainsOS agents to execution runtimes."""

from .hermes import HermesMailAdapter, WorkspaceBoundaryViolation

__all__ = ["HermesMailAdapter", "WorkspaceBoundaryViolation"]
