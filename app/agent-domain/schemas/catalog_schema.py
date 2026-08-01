"""Shapes for the flat catalogs: `steps.yaml`, `operations.yaml`, `mappings.yaml`.

The split is deliberate. A step is a runtime capability, an operation is a
domain capability with a declared parameter contract, and a mapping is the
transport detail that says which MCP tool performs an operation and where each
tool argument comes from. The runtime should never hard-code a tool name.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from schemas.playbook_schema import Playbook


# A step is either an LLM call, an operation (tool) call, or a deterministic
# transform over what earlier steps produced.
StepKind = Literal["llm", "operation", "transform"]

ParameterType = Literal["string", "integer", "number", "boolean", "array", "object"]

# Tool arguments are bound to a request parameter, a value the runtime derives
# from trusted context (never the model), or a fixed constant.
ARGUMENT_SOURCE = re.compile(r"^(param|context|const)\.(.+)$")


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StepDefinition(DomainModel):
    name: str
    kind: StepKind
    description: str


class OperationParameter(DomainModel):
    type: ParameterType
    description: str
    required: bool = False
    default: Any = None
    enum: list[Any] | None = None


class Operation(DomainModel):
    name: str
    description: str
    parameters: dict[str, OperationParameter] = Field(default_factory=dict)
    returns: str


class Mapping(DomainModel):
    operation: str
    server: str
    tool: str
    arguments: dict[str, str] = Field(default_factory=dict)
    destructive: bool = False
    requires_approval: bool = False

    @field_validator("arguments")
    @classmethod
    def _check_argument_sources(cls, arguments: dict[str, str]) -> dict[str, str]:
        invalid = sorted(
            argument
            for argument, source in arguments.items()
            if not ARGUMENT_SOURCE.match(source)
        )
        if invalid:
            raise ValueError(
                f"arguments must be bound to param.*, context.* or const.*: {invalid}"
            )
        return arguments


class Catalog(DomainModel):
    """Everything the runtime needs to boot, in one payload."""

    steps: list[StepDefinition]
    operations: list[Operation]
    mappings: list[Mapping]
    playbooks: list[Playbook]
