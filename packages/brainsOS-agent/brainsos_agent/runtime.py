"""Abstract Agent Runtime interface for brainsOS cognitive execution."""

from __future__ import annotations

from abc import ABC, abstractmethod

from brainsos_mail.models import ParsedInboundEmail

from brainsos_agent.models import AgentProfile, OutboundEmail


class AgentRuntime(ABC):
    """Core abstract SPI contract for autonomous agent execution engines."""

    @abstractmethod
    async def process_message(
        self,
        email: ParsedInboundEmail,
        profile: AgentProfile,
    ) -> OutboundEmail:
        """Processes an inbound email for an agent profile and returns a typed OutboundEmail."""
        pass
