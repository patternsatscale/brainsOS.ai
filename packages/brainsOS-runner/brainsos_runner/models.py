"""Universal Cognitive IPC Contracts and Pydantic Data Models.

Provides engine-agnostic data models allowing interchangeable LLM runners
(Hermes, OpenAI, Claude, OpenHands) across the brainsOS compute plane.
"""

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class ChatMessage(BaseModel):
    """Single chat turn in an agent conversation."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    author: Optional[str] = None
    tool_call_id: Optional[str] = None


class McpServerConfig(BaseModel):
    """Model Context Protocol (MCP) server configuration."""

    model_config = ConfigDict(extra="forbid")

    name: str
    url: str
    transport: Literal["sse", "stdio"] = "sse"


class ToolCallRecord(BaseModel):
    """Record of an executed tool invocation during a turn."""

    model_config = ConfigDict(extra="forbid")

    id: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    output: str
    exit_code: int = 0


class MemoryDelta(BaseModel):
    """Structured mutation event to be applied to an agent's memory partition."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["set", "append", "delete"]
    key: str
    value: Any = None


class ExecutionMetrics(BaseModel):
    """Execution telemetry and token metrics."""

    model_config = ConfigDict(extra="forbid")

    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    duration_ms: int = Field(default=0, ge=0)


class AgentTurnRequest(BaseModel):
    """Universal request payload dispatched to any cognitive compute runner."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    agent_id: str
    model: str
    system_prompt: str
    conversation: list[ChatMessage]
    mcp_servers: list[McpServerConfig] = Field(default_factory=list)
    workspace_dir: str
    timeout_sec: int = Field(default=120, gt=0)
    extra_params: dict[str, Any] = Field(default_factory=dict)


class AgentTurnResponse(BaseModel):
    """Universal response payload returned by any cognitive compute runner."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: Literal["completed", "failed", "timed_out"]
    output_text: str
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    memory_deltas: list[MemoryDelta] = Field(default_factory=list)
    metrics: ExecutionMetrics = Field(default_factory=ExecutionMetrics)
    error_message: Optional[str] = None
