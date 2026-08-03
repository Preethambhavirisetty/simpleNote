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


# Scalars a tool returns that ARE the answer to an analytical question - a
# count, a date, a yes/no. They live at the top level of the tool result, not
# inside the note records, so a step that only collects note records drops
# them and leaves the model to invent a number.
# Tool field -> the label the model sees. Renamed because the raw names are
# ambiguous read cold: `note_count` and `indexed_note_count` differ by one word
# and mean "matched" versus "exist in the whole workspace", and a model asked
# about January reported the workspace total as the month's total.
FACT_FIELDS = {
    "found": "topic_was_found",
    "note_count": "notes_matching_this_question",
    "mention_count": "total_mentions_across_those_notes",
    "indexed_note_count": "notes_searchable_in_whole_workspace",
    "weak_matches_excluded": "weak_matches_rejected_as_irrelevant",
    "matched_before_window": "matches_outside_the_time_window",
    "last_written_at": "most_recent_write_timestamp",
    "latest_date_mentioned": "latest_date_the_text_refers_to",
    "searched_for": "topic_actually_searched",
    "start_date": "period_start",
    "end_date": "period_end",
    "basis": "period_basis",
    "days": "window_days",
    "since": "window_started",
}


def collected_facts(state: RunState) -> dict[str, Any]:
    """Answer-bearing scalars from the tool calls in this run.

    Counting and dating questions are answered by these values, and by nothing
    else in the payload: the note records show *which* notes matched, never how
    many times. Handing the model records alone is what produced "mentioned
    food 6 times" for a tool result that said 2.
    """
    facts: dict[str, Any] = {}
    for run in state.steps:
        if not run.ok or run.call is None or not isinstance(run.output, dict):
            continue
        for field, label in FACT_FIELDS.items():
            if field in run.output and run.output[field] is not None:
                facts[label] = run.output[field]
    return facts
