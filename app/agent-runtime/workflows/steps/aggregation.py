"""Merge what earlier steps returned into one deduplicated, ranked list."""

from __future__ import annotations

from typing import Any

from schemas.playbook import PlaybookStep
from state.state import RunState, StepRun
from integrations import observability as obs
from workflows.steps.base import StepContext, collected_notes


def run(state: RunState, step: PlaybookStep, context: StepContext) -> StepRun:
    merged: dict[str, dict[str, Any]] = {}
    unkeyed: list[dict[str, Any]] = []

    for record in collected_notes(state):
        key = _identity(record)
        if key is None:
            unkeyed.append(record)
            continue
        # Two operations can return the same note with different detail; keep
        # the richer record rather than whichever arrived last.
        existing = merged.get(key)
        merged[key] = _merge(existing, record) if existing else record

    records = sorted(merged.values(), key=_rank, reverse=True) + unkeyed
    obs.debug(
        "aggregated to %d record(s)",
        len(records),
        phase="aggregation",
        data={"records": obs.preview(records), "unkeyed": len(unkeyed)},
        track={"aggregated_records": len(records), "deduplicated": len(merged)},
    )
    return StepRun(step=step.step, output={"records": records, "count": len(records)})


def _identity(record: dict[str, Any]) -> str | None:
    for key in ("note_id", "doc_id", "folder_id", "tag_id", "id"):
        value = record.get(key)
        if value:
            return f"{key}:{value}"
    return None


def _merge(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    for key, value in incoming.items():
        if value in (None, "", [], {}):
            continue
        if key not in merged or merged[key] in (None, "", [], {}):
            merged[key] = value
    return merged


def _rank(record: dict[str, Any]) -> float:
    score = record.get("best_score")
    try:
        return float(score)
    except (TypeError, ValueError):
        return 0.0
