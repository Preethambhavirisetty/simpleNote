"""Does the assistant answer *correctly*, not just route correctly?

`selector_eval.py` measures which playbook a question reaches. That is only
half the question: routing to `count_mentions` and then reporting a number the
tool never produced is still a wrong answer, and it happened - the tool
returned 2 mentions and the answer said 6.

So these assertions are about the answer text and the tool facts behind it.
They are written as properties rather than exact strings, because the wording
is a model's and will drift:

    the answer must contain the number the tool measured
    a topic that exists must not be denied
    a topic that does not exist must be denied, not hedged

Expected values come from the note corpus described in `CORPUS` below. Update
both together - a case that no longer matches the notes is a broken test, not
a broken assistant.

    .venv/bin/python -m evals.answers
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# What the corpus contains, as the assertions below assume it.
CORPUS = """
Personal : Weekend picnic plan, Picnic Shopping List, Rain Check, Summer Plans
Recepies : Sourdough Starter Log, Kitchen Equipment Wishlist (never says
           "sourdough" or "bread"), Weekend Baking Notes, Farmers Market Finds
Travel   : Boston Trip Itinerary
Work     : Conference Notes, Performance Review, Project Phoenix Retrospective,
           Q1 Planning, Sprint Backlog
General  : Food Stories, English Practice Tips (long, numbered list)
"""


@dataclass
class AnswerCase:
    question: str
    # Substrings that must appear (case-insensitive). Any one of a tuple counts.
    expect: tuple[Any, ...] = ()
    # Substrings that must NOT appear - denials of things that do exist, etc.
    reject: tuple[str, ...] = ()
    # Extra assertion over the whole response payload.
    check: Callable[[dict], str | None] | None = None
    note: str = ""


def _mentions_number(payload: dict) -> str | None:
    """The stated count must be the one the tools measured, not an estimate.

    This is the "6 times when the tool said 2" guard.
    """
    answer = str(payload.get("answer") or "")
    numbers = {int(value) for value in re.findall(r"\b(\d{1,3})\b", answer)}
    if not numbers:
        return None  # a worded answer with no number is not a fabrication
    facts = payload.get("facts") or {}
    measured = {
        int(value)
        for key, value in facts.items()
        if isinstance(value, int) and "count" in key or "mentions" in str(key)
    }
    if measured and not (numbers & measured):
        return f"answer states {sorted(numbers)} but tools measured {sorted(measured)}"
    return None


DENIALS = ("could not find", "did not", "no notes", "not mention", "nothing", "no, ")


def _must_not_deny(payload: dict) -> str | None:
    answer = str(payload.get("answer") or "").lower()
    if any(phrase in answer for phrase in DENIALS):
        return "denied a topic that exists in the corpus"
    return None


def _must_deny(payload: dict) -> str | None:
    answer = str(payload.get("answer") or "").lower()
    if not any(phrase in answer for phrase in DENIALS):
        return "did not deny a topic that is absent from the corpus"
    return None


CASES: list[AnswerCase] = [
    # ── counting: the number must come from the tool ────────────────────────
    AnswerCase(
        "How many times did I mention the picnic?",
        check=_mentions_number,
        note="4 picnic notes exist; any number given must match the tool",
    ),
    AnswerCase(
        "How many notes mention sourdough?",
        check=_mentions_number,
    ),

    # ── existence: present topics must not be denied ────────────────────────
    AnswerCase(
        "Did I ever write about visiting Boston?",
        check=_must_not_deny,
        note="Boston Trip Itinerary exists",
    ),
    AnswerCase(
        "Have I written anything about a dentist appointment?",
        check=_must_not_deny,
    ),

    # ── existence: absent topics must be denied, not hedged ─────────────────
    AnswerCase(
        "Did I ever write about quantum chromodynamics?",
        check=_must_deny,
        note="nothing in the corpus is remotely about this",
    ),
    AnswerCase(
        "How many times did I mention scuba diving?",
        check=_must_deny,
    ),

    # ── grounded content: the answer must name the right note ───────────────
    AnswerCase(
        "What do my notes say about food?",
        expect=(("food stories", "food"),),
        check=_must_not_deny,
    ),
    AnswerCase(
        "Where am I going on my trip?",
        expect=(("boston",),),
        note="Boston Trip Itinerary is the only travel note",
    ),

    # ── the second hop: a related note that never uses the seed word ────────
    AnswerCase(
        "What notes are connected to the ones about sourdough?",
        expect=(("kitchen", "equipment", "baking", "market"),),
        note="Kitchen Equipment Wishlist never says sourdough - it can only "
        "surface through the seed notes' vocabulary",
    ),

    # ── dates: written vs about ─────────────────────────────────────────────
    AnswerCase(
        "What notes did I write in January 2025?",
        check=_must_deny,
        note="the corpus was written in 2026, so this must be empty",
    ),
    AnswerCase(
        "When did I last write about baking?",
        check=_must_not_deny,
    ),

    # ── refusal path stays intact ───────────────────────────────────────────
    AnswerCase(
        "Delete my picnic note.",
        expect=(("can't change", "cannot change", "still being built"),),
        note="mutations are gated; the refusal must be the catalogued one",
    ),
]


def evaluate(payload: dict, case: AnswerCase) -> list[str]:
    problems: list[str] = []
    answer = str(payload.get("answer") or "").lower()

    for expected in case.expect:
        options = expected if isinstance(expected, tuple) else (expected,)
        if not any(option.lower() in answer for option in options):
            problems.append(f"missing any of {list(options)}")

    for rejected in case.reject:
        if rejected.lower() in answer:
            problems.append(f"should not contain {rejected!r}")

    if case.check is not None:
        problem = case.check(payload)
        if problem:
            problems.append(problem)

    return problems
