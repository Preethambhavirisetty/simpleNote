"""Drop resolved filters the upcoming operation cannot accept.

`resolve_filters` guesses structure from natural language, so it can produce a
filter that is right about intent and wrong about this operation's contract.
Rather than let the call fail, drop what does not fit and say what was dropped.
"""

from __future__ import annotations

from schemas.playbook import PlaybookStep
from state.state import RunState, StepRun
from utils import CatalogLookupError, matches_declared_type
from integrations import observability as obs
from workflows.steps.base import StepContext


def run(state: RunState, step: PlaybookStep, context: StepContext) -> StepRun:
    operation = _next_operation(state, context)
    if operation is None:
        # Nothing to validate against; leave the filters untouched.
        return StepRun(step=step.step, output={"filters": dict(state.filters), "dropped": {}})

    declared = operation.parameters
    kept: dict[str, object] = {}
    dropped: dict[str, str] = {}

    for name, value in state.filters.items():
        parameter = declared.get(name)
        if parameter is None:
            dropped[name] = f"{operation.name} declares no parameter '{name}'"
        elif not matches_declared_type(value, parameter.type):
            dropped[name] = (
                f"expects {parameter.type}, got {type(value).__name__}"
            )
        elif parameter.enum is not None and value not in parameter.enum:
            dropped[name] = f"must be one of {parameter.enum}"
        else:
            kept[name] = value

    if dropped:
        obs.warn("dropped %d filter(s) for %s", len(dropped), operation.name,
                 phase="validate_filters", data={"dropped": dropped},
                 track={"filters_dropped": len(dropped)})
    obs.debug("filters valid for %s", operation.name, phase="validate_filters",
              data={"kept": kept})
    state.filters = kept
    return StepRun(
        step=step.step,
        output={"filters": kept, "dropped": dropped, "validated_for": operation.name},
    )


def _next_operation(state: RunState, context: StepContext):
    """The operation this plan runs next, which the filters must satisfy."""
    plan = context.playbooks.get_plan(state.playbook_id, state.plan_name)
    seen = len(state.steps)
    for planned in plan.steps[seen:]:
        if planned.operation:
            try:
                return context.operations.get_operation(planned.operation)
            except CatalogLookupError:
                return None
    return None
