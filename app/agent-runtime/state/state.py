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


class PendingApproval(BaseModel):
    """A run paused for the user, either to confirm or to choose a target.

    Two shapes, one pause. `call` set means everything is resolved and the user
    is confirming a destructive action. `parameter` set means the operation
    needs an id nobody has supplied, and `choices` are the candidates found so
    far - the user picks rather than the runtime guessing, which is the whole
    point on a delete.
    """

    operation: str
    reason: str
    call: ToolCall | None = None
    parameter: str | None = None
    choices: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def needs_choice(self) -> bool:
        return self.call is None


class StepRun(BaseModel):
    """What one step of the plan did, kept so later steps can read it."""

    step: str
    operation: str | None = None
    call: ToolCall | None = None
    output: Any = None
    error: str | None = None
    # A step that stopped to ask the user something did not fail; it will run
    # again on resume, and must not be reported as an error of the run.
    paused: bool = False

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
    pending_approval: PendingApproval | None = None
    # Index of the plan step to run next; a resumed run picks up here.
    cursor: int = 0

    answer: str | None = None
    # Records behind the answer, for a UI that shows notes rather than prose.
    structured: list[Any] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    # Set when the run ends on a catalogued failure or refusal, so the API can
    # report the same code the UI switches on.
    failure_code: str | None = None
    # Set when the user approved an operation, so the resumed step may run it.
    approved_operation: str | None = None

    def record(self, run: StepRun) -> None:
        self.steps.append(run)
        if run.error and not run.paused:
            self.errors.append(f"{run.step}: {run.error}")

    def outputs(self, step: str) -> list[Any]:
        """Every successful output produced by a given step name."""
        return [run.output for run in self.steps if run.step == step and run.ok]

    @property
    def evidence(self) -> list[Any]:
        """Everything the tool-calling steps returned, in order."""
        return [run.output for run in self.steps if run.call is not None and run.ok]

    def snapshot(self) -> dict[str, Any]:
        """The run state as it stands, for a log line at a node boundary.

        Deliberately the whole shape rather than a chosen few fields: when a
        run goes wrong the useful question is usually "what did state look like
        here", and a snapshot answers it without another deploy.
        """
        return {
            "phase": self.phase,
            "cursor": self.cursor,
            "playbook": self.playbook_id,
            "plan": self.plan_name,
            "filters": dict(self.filters),
            "steps": [
                {
                    "step": run.step,
                    "operation": run.operation,
                    "tool": run.call.tool if run.call else None,
                    "ok": run.ok,
                    "paused": run.paused,
                    "error": run.error,
                    "output_shape": _shape(run.output),
                }
                for run in self.steps
            ],
            "answer_chars": len(self.answer or ""),
            "records": len(self.structured),
            "errors": list(self.errors),
            "pending_approval": (
                self.pending_approval.operation if self.pending_approval else None
            ),
        }


def _shape(value: Any) -> Any:
    """What a step returned, described rather than reproduced."""
    if isinstance(value, dict):
        return {
            key: (f"list[{len(item)}]" if isinstance(item, list) else type(item).__name__)
            for key, item in list(value.items())[:10]
        }
    if isinstance(value, list):
        return f"list[{len(value)}]"
    if isinstance(value, str):
        return f"str[{len(value)}]"
    return type(value).__name__ if value is not None else None
