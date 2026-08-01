"""Run any catalog operation through its MCP tool mapping."""

from __future__ import annotations

import logging
from typing import Any

from integrations.mcp import ApprovalRequired, McpError, call_tool
from schemas.playbook import PlaybookStep
from state.state import RunState, StepRun
from utils import CatalogLookupError, OperationArgumentError
from workflows.steps.base import StepContext, failed


log = logging.getLogger(__name__)


def run(state: RunState, step: PlaybookStep, context: StepContext) -> StepRun:
    if not step.operation:
        return failed(step, "step requires an operation but the plan named none")

    parameters = parameters_for(state, step.operation, context)
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
        state.pending_approval = call
        state.phase = "awaiting_approval"
        return StepRun(
            step=step.step,
            operation=step.operation,
            call=call,
            error="awaiting approval",
        )
    except McpError as exc:
        return StepRun(step=step.step, operation=step.operation, call=call, error=str(exc))

    return StepRun(step=step.step, operation=step.operation, call=call, output=output)


def parameters_for(
    state: RunState, operation: str, context: StepContext
) -> dict[str, Any]:
    """Build this operation's parameters from the run so far.

    Only parameters the operation actually declares are offered - anything else
    would be rejected by `resolve_call`, and rightly so. Filters resolved
    earlier in the plan win; the question fills any query parameter.
    """
    declared = set(context.operations.get_operation(operation).parameters)
    parameters = {
        name: value
        for name, value in state.filters.items()
        if name in declared and value is not None
    }
    if "query" in declared and "query" not in parameters:
        parameters["query"] = state.question
    return parameters
