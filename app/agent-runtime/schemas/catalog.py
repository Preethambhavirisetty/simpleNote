"""Runtime-side view of the step, operation, and mapping catalogs.

Lenient for the same reason as `schemas/playbook.py`: the domain owns these
shapes, the runtime only consumes them.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from schemas.playbook import Playbook


StepKind = Literal["llm", "operation", "transform"]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class StepDefinition(ContractModel):
    name: str
    kind: StepKind
    description: str


class OperationParameter(ContractModel):
    type: str
    description: str = ""
    required: bool = False
    default: Any = None
    enum: list[Any] | None = None


class Operation(ContractModel):
    name: str
    description: str
    parameters: dict[str, OperationParameter] = {}
    returns: str = ""


class Mapping(ContractModel):
    operation: str
    server: str
    tool: str
    arguments: dict[str, str] = {}
    destructive: bool = False
    requires_approval: bool = False


class Catalog(ContractModel):
    steps: list[StepDefinition] = []
    operations: list[Operation] = []
    mappings: list[Mapping] = []
    playbooks: list[Playbook] = []


class ToolCall(BaseModel):
    """A mapping resolved against real parameters — ready for the MCP client."""

    operation: str
    server: str
    tool: str
    arguments: dict[str, Any]
    destructive: bool = False
    requires_approval: bool = False
