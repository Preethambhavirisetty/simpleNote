"""Run any catalog operation through its MCP tool mapping."""

from __future__ import annotations

import logging
from typing import Any

from integrations.mcp import ApprovalRequired, McpError, call_tool
from schemas.catalog import Operation
from schemas.playbook import PlaybookStep
from state.state import PendingApproval, RunState, StepRun
from utils import CatalogLookupError, OperationArgumentError
from workflows.steps.base import StepContext, collected_notes, failed


log = logging.getLogger(__name__)

# Identifier parameters a preceding step can propose candidates for, mapped to
# the field a record carries them in.
TARGET_FIELDS = {
    "note_id": "note_id",
    "folder_id": "folder_id",
    "tag_id": "tag_id",
}
MAX_CHOICES = 8


def run(state: RunState, step: PlaybookStep, context: StepContext) -> StepRun:
    if not step.operation:
        return failed(step, "step requires an operation but the plan named none")

    try:
        declared = context.operations.get_operation(step.operation)
    except CatalogLookupError as exc:
        return failed(step, str(exc))

    parameters = parameters_for(state, declared)

    missing = _missing_target(declared, parameters)
    if missing:
        return _ask_for_target(state, step, declared, missing)

    try:
        call = context.operations.resolve_call(
            step.operation, parameters, state.context.bindable()
        )
    except (CatalogLookupError, OperationArgumentError) as exc:
        return failed(step, str(exc))

    try:
        output = call_tool(call, approved=context.approved)
    except ApprovalRequired:
        # Not an error: the run pauses and resumes once the user confirms.
        state.pending_approval = PendingApproval(
            operation=step.operation,
            reason=f"{step.operation} changes your workspace and needs confirmation",
            call=call,
        )
        state.phase = "awaiting_approval"
        return StepRun(
            step=step.step,
            operation=step.operation,
            call=call,
            error="awaiting approval",
            paused=True,
        )
    except McpError as exc:
        return StepRun(step=step.step, operation=step.operation, call=call, error=str(exc))

    return StepRun(step=step.step, operation=step.operation, call=call, output=output)


def parameters_for(state: RunState, operation: Operation) -> dict[str, Any]:
    """Build this operation's parameters from the run so far.

    Only parameters the operation declares are offered - anything else would be
    rejected by `resolve_call`, and rightly so. Filters resolved earlier in the
    plan win; the question fills any query parameter.
    """
    declared = set(operation.parameters)
    parameters = {
        name: value
        for name, value in state.filters.items()
        if name in declared and value is not None
    }
    if "query" in declared and "query" not in parameters:
        parameters["query"] = state.question
    return parameters


def _missing_target(operation: Operation, parameters: dict[str, Any]) -> str | None:
    for name, spec in operation.parameters.items():
        if spec.required and name in TARGET_FIELDS and name not in parameters:
            return name
    return None


def _ask_for_target(
    state: RunState, step: PlaybookStep, operation: Operation, parameter: str
) -> StepRun:
    """Pause and let the user pick which note, folder, or tag this acts on.

    The runtime deliberately does not choose for them. Picking the top search
    hit reads as helpful right up until it deletes the wrong note.
    """
    choices = _candidates(state, parameter)
    if not choices:
        return failed(
            step,
            f"{operation.name} needs a {parameter} and nothing in this run found one",
        )

    state.pending_approval = PendingApproval(
        operation=operation.name,
        reason=f"Which one should {operation.name} act on?",
        parameter=parameter,
        choices=choices,
    )
    state.phase = "awaiting_approval"
    return StepRun(
        step=step.step,
        operation=operation.name,
        error="awaiting target choice",
        paused=True,
    )


def _candidates(state: RunState, parameter: str) -> list[dict[str, Any]]:
    field = TARGET_FIELDS[parameter]
    seen: set[str] = set()
    choices: list[dict[str, Any]] = []

    for record in collected_notes(state):
        value = record.get(field)
        if not value or str(value) in seen:
            continue
        seen.add(str(value))
        choices.append(
            {
                parameter: value,
                "label": record.get("title") or record.get("name") or str(value),
                "folder": record.get("folder"),
            }
        )
        if len(choices) >= MAX_CHOICES:
            break
    return choices
