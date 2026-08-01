"""Perform one explicit workspace action the user asked for.

Same execution path as any other operation. It exists separately because these
are the mutating calls: they are the ones that pause for approval, and keeping
them a named step makes that visible in the plan rather than buried in a flag.
"""

from __future__ import annotations

from schemas.playbook import PlaybookStep
from state.state import RunState, StepRun
from workflows.steps import execute_operation
from workflows.steps.base import StepContext


def run(state: RunState, step: PlaybookStep, context: StepContext) -> StepRun:
    return execute_operation.run(state, step, context)
