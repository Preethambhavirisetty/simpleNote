"""Retrieve evidence or note references for the question.

Identical mechanics to `execute_operation` - the distinction is declarative,
so a plan can say "this step is the retrieval step" and later steps, logging,
and evidence gates can tell retrieval apart from an arbitrary operation.
"""

from __future__ import annotations

from schemas.playbook import PlaybookStep
from state.state import RunState, StepRun
from workflows.steps import execute_operation
from workflows.steps.base import StepContext


def run(state: RunState, step: PlaybookStep, context: StepContext) -> StepRun:
    return execute_operation.run(state, step, context)
