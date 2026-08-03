"""Write the user-facing answer from what the earlier steps gathered."""

from __future__ import annotations

import json
from typing import Any

from integrations.llm import llm_call_general
from schemas.playbook import PlaybookStep
from state.state import RunState, StepRun
from utils import load_prompt
from integrations import observability as obs
from workflows.steps.base import StepContext, collected_facts, collected_notes, failed


MAX_TOKENS = 900
TEMPERATURE = 0.2
MAX_RECORDS = 12
MAX_EVIDENCE_CHARS = 6000


def run(state: RunState, step: PlaybookStep, context: StepContext) -> StepRun:
    records = _records(state)
    facts = collected_facts(state)
    evidence = _evidence(state)
    obs.debug(
        "summarising from %d record(s)",
        len(records),
        phase="summarize",
        data={
            "evidence_chars": len(evidence),
            "records": obs.preview(records),
            "facts": facts,
        },
        track={"evidence_records": len(records), "evidence_chars": len(evidence)},
    )
    if not evidence and not facts:
        obs.warn("no evidence gathered; refusing to answer from model knowledge",
                 phase="summarize", track={"ungrounded_refusal": True})
        # Say so rather than letting the model fill the gap from its own
        # knowledge - an ungrounded answer here would look identical to a
        # grounded one.
        state.answer = (
            "I could not find anything in your notes about that."
        )
        return StepRun(step=step.step, output=state.answer)

    prompt = load_prompt("summarize")
    answer = llm_call_general(
        [
            {"role": "system", "content": prompt["system"]},
            {
                "role": "user",
                "content": prompt["user"].format(
                    question=state.question,
                    evidence=evidence or "(no passages)",
                    facts=json.dumps(facts, default=str) if facts else "(none)",
                ),
            },
        ],
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
    ).strip()

    if not answer:
        return failed(step, "the model returned an empty answer")

    state.answer = answer
    return StepRun(step=step.step, output=answer)


def _evidence(state: RunState) -> str:
    records = _records(state)[:MAX_RECORDS]
    if not records:
        return ""

    blocks = []
    for record in records:
        blocks.append(json.dumps(_trimmed(record), ensure_ascii=False, default=str))
    text = "\n".join(blocks)
    return text[:MAX_EVIDENCE_CHARS]


def _records(state: RunState) -> list[dict[str, Any]]:
    for run_record in reversed(state.steps):
        if run_record.ok and isinstance(run_record.output, dict):
            records = run_record.output.get("records")
            if isinstance(records, list):
                return [item for item in records if isinstance(item, dict)]
    return collected_notes(state)


def _trimmed(record: dict[str, Any]) -> dict[str, Any]:
    """Keep what an answer needs to cite; drop retrieval bookkeeping."""
    keep = (
        "note_id", "title", "folder", "summary", "snippets",
        "updated_at", "created_at", "name", "content_text",
    )
    trimmed = {key: record[key] for key in keep if record.get(key)}
    chunks = record.get("chunks")
    if isinstance(chunks, list):
        trimmed["snippets"] = [
            chunk.get("snippet") for chunk in chunks[:3]
            if isinstance(chunk, dict) and chunk.get("snippet")
        ]
    return trimmed
