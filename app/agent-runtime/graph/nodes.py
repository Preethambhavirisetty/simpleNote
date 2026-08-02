"""The nodes of a run. Each takes the state, does one thing, and returns it.

Nodes own phase transitions; `edges.next_node` only reads the phase. Keeping
that one-directional means the routing table can be understood without reading
any node body.
"""

from __future__ import annotations

import logging

from graph.context import STEP_RUNNERS, RunContext
from graph.validators import plan_problems
from integrations.domain import DomainUnavailableError
from state.state import RunState, StepRun

log = logging.getLogger(__name__)


def route(state: RunState, context: RunContext) -> RunState:
    """Choose the playbook and plan for the question."""
    try:
        selection = context.selector.select(state.question, state.context.history)
    except DomainUnavailableError as exc:
        state.errors.append(f"routing failed: {exc}")
        state.phase = "failed"
        return state

    state.playbook_id = selection.playbook_id
    state.plan_name = selection.plan_name
    state.selection_reason = selection.reason

    problems = plan_problems(state, context)
    if problems:
        # The router picked something this runtime cannot run. Refusing beats
        # half-executing a plan and answering as if it had worked.
        state.errors += problems
        state.phase = "failed"
        return state

    log.info(
        "routed",
        extra={
            "playbook": selection.playbook_id,
            "plan": selection.plan_name,
            "mode": selection.selection_mode,
            "llm_calls": selection.llm_calls,
        },
    )
    state.phase = "executing"
    return state


def execute(state: RunState, context: RunContext) -> RunState:
    """Run the next step of the plan."""
    plan = context.playbooks.get_plan(state.playbook_id, state.plan_name)
    if state.cursor >= len(plan.steps):
        state.phase = "answering"
        return state

    step = plan.steps[state.cursor]
    runner = STEP_RUNNERS[step.step]

    approved = state.pending_approval is None and _just_approved(state)
    result = runner(state, step, context.steps(approved=approved))
    state.record(result)

    if state.phase == "awaiting_approval":
        # The step parked itself; do not advance, so resuming re-runs it.
        return state

    state.cursor += 1
    if not result.ok and _fatal(state, result):
        state.phase = "failed"
        return state

    if state.cursor >= len(plan.steps):
        state.phase = "answering"
    return state


def approve(state: RunState, context: RunContext, *, choice: str | None = None) -> RunState:
    """Apply the user's decision and let the paused step run again."""
    pending = state.pending_approval
    if pending is None:
        state.phase = "executing"
        return state

    if pending.needs_choice:
        if not choice:
            state.errors.append(f"{pending.operation} needs a {pending.parameter}")
            state.phase = "failed"
            return state
        state.filters[pending.parameter] = choice

    state.pending_approval = None
    state.approved_operation = pending.operation
    state.phase = "executing"
    return state


def answer(state: RunState, context: RunContext) -> RunState:
    """Make sure the run ends with something to say."""
    if not state.answer:
        # No LLM step in this plan wrote prose, so report what happened rather
        # than inventing a narrative over it.
        records = _records(state)
        action = _last_action(state)
        if action is not None:
            # A plan that changed something must say so. Reporting "nothing
            # found" after a successful delete is worse than saying nothing.
            state.answer = f"Done - {action.operation} completed."
            state.structured = [action.output] if isinstance(action.output, dict) else []
        elif records:
            state.answer = f"Found {len(records)} matching item(s)."
            state.structured = records
        else:
            state.answer = "I could not find anything matching that."

    state.phase = "done"
    return state


def fail(state: RunState, context: RunContext) -> RunState:
    if not state.answer:
        state.answer = (
            "I could not complete that request. " + "; ".join(state.errors[-2:])
        )
    return state


def _just_approved(state: RunState) -> bool:
    return getattr(state, "approved_operation", None) is not None


def _fatal(state: RunState, result: StepRun) -> bool:
    """Whether a failed step should end the run.

    A failed tool call is fatal - everything after it would be answering from
    nothing. A failed transform or filter step is not: the plan can continue
    with unfiltered, unsorted data and still produce a useful answer.
    """
    return result.call is not None or result.step in {"direct_llm", "summarize"}


def _last_action(state: RunState) -> StepRun | None:
    """The last mutation this run performed, if any."""
    for run_record in reversed(state.steps):
        if run_record.ok and run_record.step == "direct_tool" and run_record.call:
            return run_record
    return None


def _records(state: RunState) -> list:
    for run_record in reversed(state.steps):
        if run_record.ok and isinstance(run_record.output, dict):
            records = run_record.output.get("records")
            if isinstance(records, list):
                return records
    return []
