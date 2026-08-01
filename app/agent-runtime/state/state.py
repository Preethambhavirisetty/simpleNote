"""The working memory of one run.

`RuntimeContext` is the trusted half: values the host application derived from
an authenticated session. It is the only source for the `context.*` bindings in
the domain's mappings, which is what keeps `user_id` out of the model's reach —
there is no parameter for it, so nothing the model emits can set it.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from schemas.catalog import ToolCall


Phase = Literal["routing", "executing", "awaiting_approval", "answering", "done", "failed"]


class Message(BaseModel):
    role: str
    content: str


class RuntimeContext(BaseModel):
    """Server-derived facts. Never populated from model output."""

    model_config = ConfigDict(extra="forbid")

    user_id: str
    role: str = "user"
    history: list[Message] = Field(default_factory=list)

    def bindable(self) -> dict[str, Any]:
        """The shape `OperationLoader.resolve_call` reads `context.*` from."""
        return {
            "user_id": self.user_id,
            "role": self.role,
            "history": [message.model_dump() for message in self.history],
        }


class StepRun(BaseModel):
    """What one step of the plan did, kept so later steps can read it."""

    step: str
    operation: str | None = None
    call: ToolCall | None = None
    output: Any = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


class RunState(BaseModel):
    """Threaded through the graph; every node reads and returns updates."""

    question: str
    context: RuntimeContext

    phase: Phase = "routing"

    # Routing decision, filled by the selector.
    playbook_id: str | None = None
    plan_name: str | None = None
    selection_reason: str | None = None

    # Execution.
    filters: dict[str, Any] = Field(default_factory=dict)
    steps: list[StepRun] = Field(default_factory=list)
    pending_approval: ToolCall | None = None

    answer: str | None = None
    errors: list[str] = Field(default_factory=list)

    def record(self, run: StepRun) -> None:
        self.steps.append(run)
        if run.error:
            self.errors.append(f"{run.step}: {run.error}")

    def outputs(self, step: str) -> list[Any]:
        """Every successful output produced by a given step name."""
        return [run.output for run in self.steps if run.step == step and run.ok]

    @property
    def evidence(self) -> list[Any]:
        """Everything the tool-calling steps returned, in order."""
        return [run.output for run in self.steps if run.call is not None and run.ok]
