"""Configuration models for brainsOS runner registry."""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RunnerConfig(BaseModel):
    """Configuration definition for a single cognitive runner node or sandbox."""

    model_config = ConfigDict(extra="forbid")

    id: str
    type: Literal["warm_http", "ephemeral_docker", "local_script"]
    name: Optional[str] = None
    endpoint: Optional[str] = None
    image: Optional[str] = None
    timeout_sec: int = Field(default=120, gt=0)
    concurrency_limit: int = Field(default=4, gt=0)
    memory_limit: Optional[str] = None
    cpu_limit: Optional[str] = None
    script_path: Optional[str] = None

    @model_validator(mode="after")
    def validate_type_requirements(self) -> "RunnerConfig":
        if self.type == "warm_http" and not self.endpoint:
            raise ValueError("Runner of type 'warm_http' requires an 'endpoint'")
        if self.type == "ephemeral_docker" and not self.image:
            raise ValueError("Runner of type 'ephemeral_docker' requires an 'image'")
        if self.type == "local_script" and not self.script_path:
            raise ValueError("Runner of type 'local_script' requires a 'script_path'")
        return self
