"""What every step is handed, and what it must give back.

A step reads the run state and returns one `StepRun` describing what it did.
Steps never mutate state themselves - the caller records the result - so a step
is a pure-ish function that is easy to run in isolation and easy to replay.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from loaders.operation_loader import OperationLoader
from loaders.playbook_loader import PlaybookLoader
from schemas.playbook import PlaybookStep
from state.state import RunState, StepRun


@dataclass(frozen=True)
class StepContext:
    """Everything a step is allowed to reach for."""

    operations: OperationLoader
    playbooks: PlaybookLoader
    # Set once a destructive call has been confirmed by the caller, so the
    # approval gate in the MCP client lets it through.
    approved: bool = False


class Step(Protocol):
    def __call__(
        self, state: RunState, step: PlaybookStep, context: StepContext
    ) -> StepRun: ...


def failed(step: PlaybookStep, error: str) -> StepRun:
    return StepRun(step=step.step, operation=step.operation, error=error)


def collected_notes(state: RunState) -> list[dict[str, Any]]:
    """Note records gathered so far, from whichever tool produced them.

    Retrieval and listing operations return different envelopes - `notes` for
    the search tools, `notes` for list_notes, `summaries` for summarize_notes -
    so transforms downstream read through this rather than knowing which
    operation ran.
    """
    notes: list[dict[str, Any]] = []
    for run in state.steps:
        if not run.ok or not isinstance(run.output, dict):
            continue
        for key in ("notes", "summaries", "folders", "tags"):
            values = run.output.get(key)
            if isinstance(values, list):
                notes.extend(item for item in values if isinstance(item, dict))
    return notes
