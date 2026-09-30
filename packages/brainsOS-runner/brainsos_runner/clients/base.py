"""Base cognitive runner client interface."""

from abc import ABC, abstractmethod

from brainsos_runner.models import AgentTurnRequest, AgentTurnResponse


class RunnerClient(ABC):
    """Abstract base interface for all brainsOS cognitive runner clients."""

    @abstractmethod
    async def execute_turn(self, request: AgentTurnRequest) -> AgentTurnResponse:
        """Execute a cognitive turn against the underlying runner substrate."""
        pass
