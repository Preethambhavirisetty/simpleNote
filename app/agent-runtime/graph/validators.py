"""Check a selected plan is runnable before any of it runs."""

from __future__ import annotations

from graph.context import STEP_RUNNERS, RunContext
from state.state import RunState
from utils import CatalogLookupError


def plan_problems(state: RunState, context: RunContext) -> list[str]:
    """Reasons this runtime cannot execute the plan the router chose.

    The domain validates its own catalog, but it cannot know which steps this
    runtime actually implements - a domain deployed ahead of a runtime can
    declare a step that does not exist here yet.
    """
    try:
        plan = context.playbooks.get_plan(state.playbook_id, state.plan_name)
    except CatalogLookupError as exc:
        return [str(exc)]

    problems = []
    for step in plan.steps:
        if step.step not in STEP_RUNNERS:
            problems.append(f"step '{step.step}' is not implemented by this runtime")
        if step.operation:
            try:
                context.operations.get_mapping(step.operation)
            except CatalogLookupError as exc:
                problems.append(str(exc))
    return problems
