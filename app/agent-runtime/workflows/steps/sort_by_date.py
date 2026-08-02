"""Order the collected notes newest first, so a timeline reads as one."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from schemas.playbook import PlaybookStep
from state.state import RunState, StepRun
from integrations import observability as obs
from workflows.steps.base import StepContext, collected_notes


# Newest first, and the field that best represents "when this happened".
DATE_FIELDS = ("updated_at", "summary_generated_at", "created_at")


def run(state: RunState, step: PlaybookStep, context: StepContext) -> StepRun:
    records = _records(state)
    dated = [(_timestamp(record), record) for record in records]

    # Records with no usable date go last rather than being dropped or sorted
    # as if they were ancient.
    known = sorted(
        (item for item in dated if item[0] is not None),
        key=lambda item: item[0],
        reverse=True,
    )
    unknown = [item for item in dated if item[0] is None]

    ordered = [record for _, record in known] + [record for _, record in unknown]
    obs.debug(
        "sorted %d dated, %d undated",
        len(known),
        len(unknown),
        phase="sort_by_date",
        data={"order": [r.get("title") or r.get("note_id") for r in ordered[:8]]},
        track={"undated_records": len(unknown)},
    )
    return StepRun(
        step=step.step,
        output={
            "records": ordered,
            "count": len(ordered),
            "undated": len(unknown),
        },
    )


def _records(state: RunState) -> list[dict[str, Any]]:
    """Prefer what aggregation produced; fall back to raw tool output."""
    for run_record in reversed(state.steps):
        if run_record.ok and isinstance(run_record.output, dict):
            records = run_record.output.get("records")
            if isinstance(records, list):
                return [item for item in records if isinstance(item, dict)]
    return collected_notes(state)


def _timestamp(record: dict[str, Any]) -> datetime | None:
    for field in DATE_FIELDS:
        value = record.get(field)
        if not value:
            continue
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            continue
    return None
