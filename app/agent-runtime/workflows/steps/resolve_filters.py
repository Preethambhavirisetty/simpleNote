"""Turn the question into structured filters the operations can accept.

Only filters the model is confident about are kept: a wrong folder or date
range silently returns the wrong notes, which is worse than no filter at all.
`validate_filters` then drops anything the next operation cannot take.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any

from integrations.llm import llm_call_general
from schemas.playbook import PlaybookStep
from state.state import RunState, StepRun
from integrations import observability as obs
from utils import load_prompt
from workflows.steps.base import StepContext


log = logging.getLogger(__name__)

MAX_TOKENS = 250
TEMPERATURE = 0.0
_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def run(state: RunState, step: PlaybookStep, context: StepContext) -> StepRun:
    prompt = load_prompt("resolve_filters")
    completion = llm_call_general(
        [
            {"role": "system", "content": prompt["system"]},
            {
                "role": "user",
                "content": prompt["user"].format(
                    question=state.question,
                    # A period like "last March" cannot be resolved without it.
                    today=date.today().isoformat(),
                ),
            },
        ],
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
    )

    obs.debug("filter model said: %s", obs.preview(completion, 300), phase="resolve_filters")
    filters = _parse(completion)
    # Filters are an optimisation, never a requirement: an unparseable answer
    # means search the whole workspace, not fail the run.
    if filters is None:
        log.info("no filters resolved", extra={"completion": completion[:200]})
        filters = {}

    obs.info("resolved filters: %s", filters, phase="resolve_filters",
             data={"filters": filters}, track={"filter_count": len(filters)})
    state.filters.update(filters)
    return StepRun(step=step.step, output={"filters": filters})


def _parse(completion: str) -> dict[str, Any] | None:
    match = _JSON_OBJECT.search(completion or "")
    if match is None:
        return None
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return {
        str(key): value
        for key, value in payload.items()
        if value not in (None, "", [], {})
    }
