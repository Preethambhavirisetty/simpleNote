from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Sequence
from typing import Any

from config import PLAYBOOK_SELECTION_MODE
from integrations import observability as obs
from integrations.domain import fetch_candidates
from integrations.llm import llm_call_general
from loaders.playbook_loader import PlaybookLoader
from schemas.playbook import Playbook, PlaybookSelection
from state.state import Message
from utils import CatalogLookupError, load_prompt


log = logging.getLogger(__name__)

MAX_EXAMPLES = 4
MAX_HISTORY = 6
SELECTOR_MAX_TOKENS = 200
SELECTOR_TEMPERATURE = 0.0

# Where to land when the model's answer is unusable. Deliberately a grounded
# playbook: a router miss should send the run to look at the user's notes, not
# to answer from the model's own knowledge.
FALLBACK = ("notes_qa", "answer_from_notes")

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)

RETRY_NUDGE = (
    "That answer could not be used: {problem}\n\n"
    "Reply again with only the JSON object, all fields present, reason first. "
    "Choose from exactly these:\n{valid}"
)

# A parse returns the value it found, or None plus what was wrong.
Parsed = tuple[Any, None] | tuple[None, str]


class PlaybookSelector:
    """Picks the playbook and plan for one request.

    Two strategies, chosen by `mode`:

    "single" - one call decides both. The judgement that a request wants an
    answer rather than a list is the same judgement that picks between that
    playbook's plans, so keeping them together gives one coherent decision and
    one round trip.

    "split" - one call picks the playbook, a second picks the plan from only
    that playbook's plans. Costs a second round trip and cannot reconsider the
    playbook, but the second prompt physically cannot contain a plan from
    another playbook, so cross-level confusion is impossible by construction.

    Both get the same treatment on a bad answer: one corrective retry naming
    the problem and the legal choices, then the fallback. Which strategy is
    better is an empirical question about plan accuracy - see
    `evals/selector_eval.py`.
    """

    def __init__(
        self, playbooks: PlaybookLoader, mode: str = PLAYBOOK_SELECTION_MODE
    ) -> None:
        if mode not in {"single", "split"}:
            raise ValueError(f"unknown selection mode '{mode}'")
        self._playbooks = playbooks
        self._mode = mode

    def select(
        self, question: str, history: Sequence[Message] | None = None
    ) -> PlaybookSelection:
        with obs.timed("route", "fetch candidates") as timer:
            candidates = fetch_candidates(question)
            timer.track(
                candidate_count=len(candidates.playbooks),
                candidate_mode=candidates.selection_mode,
            )
        obs.debug(
            "candidates: %s",
            [p.playbook_id for p in candidates.playbooks],
            phase="route",
            data={"mode": candidates.selection_mode},
        )
        chooser = self._select_split if self._mode == "split" else self._select_single
        return chooser(
            candidates.playbooks, candidates.selection_mode, question, history
        )

    # ── single-call strategy ────────────────────────────────────────────────

    def _select_single(
        self,
        playbooks: Sequence[Playbook],
        selection_mode: str,
        question: str,
        history: Sequence[Message] | None,
    ) -> PlaybookSelection:
        prompt = load_prompt("playbook_selector")
        messages = self._messages(
            prompt["system"],
            prompt["user"],
            history=history,
            question=question,
            catalog=self._render_catalog(playbooks, with_plans=True),
        )

        chosen, problem, calls = self._ask(
            messages,
            self._parse_pair,
            lambda completion: self._repair_options(playbooks, completion),
        )
        if chosen is None:
            return self._fallback(problem, calls)

        playbook_id, plan_name, reason = chosen
        return PlaybookSelection(
            playbook_id=playbook_id,
            plan_name=plan_name,
            reason=reason or "no reason given",
            selection_mode=selection_mode,
            llm_calls=calls,
        )

    # ── split strategy ──────────────────────────────────────────────────────

    def _select_split(
        self,
        playbooks: Sequence[Playbook],
        selection_mode: str,
        question: str,
        history: Sequence[Message] | None,
    ) -> PlaybookSelection:
        prompt = load_prompt("playbook_selector")
        messages = self._messages(
            prompt["system_playbook_only"],
            prompt["user"],
            history=history,
            question=question,
            catalog=self._render_catalog(playbooks, with_plans=False),
        )
        ids = "\n".join(f"  {playbook.playbook_id}" for playbook in playbooks)

        chosen, problem, calls = self._ask(
            messages, self._parse_playbook, lambda _completion: ids
        )
        if chosen is None:
            return self._fallback(problem, calls)

        playbook_id, playbook_reason = chosen
        playbook = self._playbooks.get_playbook(playbook_id)

        # A playbook with one plan has nothing to decide; skip the second call.
        if len(playbook.plans) == 1:
            return PlaybookSelection(
                playbook_id=playbook_id,
                plan_name=playbook.plans[0].name,
                reason=playbook_reason or "no reason given",
                selection_mode=selection_mode,
                llm_calls=calls,
            )

        plan_prompt = load_prompt("plan_selector")
        plan_messages = self._messages(
            plan_prompt["system"],
            plan_prompt["user"],
            history=history,
            question=question,
            playbook_id=playbook.playbook_id,
            playbook_purpose=self._one_line(playbook.description),
            plans=self._render_plans(playbook),
        )
        names = " | ".join(plan.name for plan in playbook.plans)

        picked, problem, plan_calls = self._ask(
            plan_messages,
            lambda completion: self._parse_plan(completion, playbook_id),
            lambda _completion: f"  plans of {playbook_id}: {names}",
        )
        calls += plan_calls
        if picked is None:
            return self._fallback(problem, calls)

        plan_name, plan_reason = picked
        return PlaybookSelection(
            playbook_id=playbook_id,
            plan_name=plan_name,
            reason=plan_reason or playbook_reason or "no reason given",
            selection_mode=selection_mode,
            llm_calls=calls,
        )

    # ── asking ──────────────────────────────────────────────────────────────

    def _ask(
        self,
        messages: list[dict[str, str]],
        parse: Callable[[str], Parsed],
        options: Callable[[str], str],
    ) -> tuple[Any | None, str | None, int]:
        """One call, then one corrective retry naming what went wrong.

        Told the exact problem and the legal choices, a small model usually
        fixes a swapped level or a missing field - cheaper than losing the
        decision to the fallback.
        """
        obs.debug(
            "selector prompt",
            phase="route",
            data={"chars": sum(len(m["content"]) for m in messages)},
        )
        completion = self._complete(messages)
        obs.debug("selector said: %s", obs.preview(completion, 300), phase="route")
        value, problem = parse(completion)
        if value is not None:
            return value, None, 1

        obs.warn("selector answer unusable: %s", problem, phase="route")

        retry = messages + [
            {"role": "assistant", "content": completion},
            {
                "role": "user",
                "content": RETRY_NUDGE.format(
                    problem=problem, valid=options(completion)
                ),
            },
        ]
        retried = self._complete(retry)
        value, problem = parse(retried)
        if value is not None:
            log.info("selector recovered on retry")
            obs.info("selector recovered on retry", phase="route", track={"selector_retried": True})
        else:
            obs.error("selector failed twice: %s", problem, phase="route",
                      track={"selector_fallback": True})
            log.warning(
                "selector failed twice",
                extra={"problem": problem, "completion": retried[:200]},
            )
        return value, problem, 2

    @staticmethod
    def _complete(messages: list[dict[str, str]]) -> str:
        return llm_call_general(
            messages,
            max_tokens=SELECTOR_MAX_TOKENS,
            temperature=SELECTOR_TEMPERATURE,
        )

    # ── parsing ─────────────────────────────────────────────────────────────

    def _parse_pair(self, completion: str) -> Parsed:
        payload = self._extract_json(completion)
        if payload is None:
            return None, "the answer contained no JSON object"

        playbook_id = str(payload.get("playbook_id", "")).strip()
        plan_name = str(payload.get("plan", "")).strip()
        try:
            # Validating against the catalog is what makes a hallucinated name
            # a caught error rather than a step that silently never runs.
            self._playbooks.get_plan(playbook_id, plan_name)
        except CatalogLookupError as exc:
            return None, str(exc)

        return (playbook_id, plan_name, str(payload.get("reason", "")).strip()), None

    def _parse_playbook(self, completion: str) -> Parsed:
        payload = self._extract_json(completion)
        if payload is None:
            return None, "the answer contained no JSON object"

        playbook_id = str(payload.get("playbook_id", "")).strip()
        try:
            self._playbooks.get_playbook(playbook_id)
        except CatalogLookupError as exc:
            return None, str(exc)

        return (playbook_id, str(payload.get("reason", "")).strip()), None

    def _parse_plan(self, completion: str, playbook_id: str) -> Parsed:
        payload = self._extract_json(completion)
        if payload is None:
            return None, "the answer contained no JSON object"

        plan_name = str(payload.get("plan", "")).strip()
        try:
            self._playbooks.get_plan(playbook_id, plan_name)
        except CatalogLookupError as exc:
            return None, str(exc)

        return (plan_name, str(payload.get("reason", "")).strip()), None

    @staticmethod
    def _extract_json(completion: str) -> dict | None:
        """Tolerate a fenced or chatty answer around the JSON object."""
        match = _JSON_OBJECT.search(completion or "")
        if match is None:
            return None
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    def _fallback(self, problem: str | None, calls: int) -> PlaybookSelection:
        playbook_id, plan_name = FALLBACK
        return PlaybookSelection(
            playbook_id=playbook_id,
            plan_name=plan_name,
            reason=f"Fell back to the grounded default: {problem}",
            selection_mode="fallback",
            llm_calls=calls,
        )

    # ── rendering ───────────────────────────────────────────────────────────

    @staticmethod
    def _messages(system: str, user: str, **fields: Any) -> list[dict[str, str]]:
        history = fields.pop("history", None)
        question = str(fields.pop("question", "")).strip()
        return [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": user.format(
                    history=PlaybookSelector._render_history(history),
                    question=question,
                    **fields,
                ),
            },
        ]

    def _repair_options(
        self, playbooks: Sequence[Playbook], completion: str
    ) -> str:
        """Narrow the retry to one playbook's plans when the playbook was right.

        A model that picked a real playbook and a bad plan does not need the
        whole catalog again - it needs the plans it was choosing between.

        Except when the plan it named is real but lives elsewhere: then the
        plan was the accurate signal and the playbook was the mistake, so
        narrowing to the wrong playbook would trap it there. Point at the
        owner instead and let it correct in either direction.
        """
        payload = self._extract_json(completion) or {}
        chosen = str(payload.get("playbook_id", "")).strip()
        named_plan = str(payload.get("plan", "")).strip()
        everything = "\n".join(
            f"  {playbook.playbook_id}: "
            + " | ".join(plan.name for plan in playbook.plans)
            for playbook in playbooks
        )

        owners = [
            playbook.playbook_id
            for playbook in playbooks
            if any(plan.name == named_plan for plan in playbook.plans)
        ]
        if named_plan and chosen not in owners and owners:
            return (
                f"  plan \"{named_plan}\" belongs to playbook "
                f"\"{owners[0]}\", not \"{chosen}\". Either pick that playbook, "
                f"or pick a plan that does belong to yours:\n{everything}"
            )

        for playbook in playbooks:
            if playbook.playbook_id == chosen:
                plans = " | ".join(plan.name for plan in playbook.plans)
                return f'  playbook_id "{chosen}" with one of these plans: {plans}'
        return everything

    @staticmethod
    def _one_line(text: str) -> str:
        return " ".join(text.split())

    @classmethod
    def _render_plans(cls, playbook: Playbook) -> str:
        return "\n".join(
            f"  - {plan.name}: {cls._one_line(plan.description)}"
            for plan in playbook.plans
        )

    @staticmethod
    def _render_history(history: Sequence[Message] | None) -> str:
        if not history:
            return ""
        recent = list(history)[-MAX_HISTORY:]
        lines = "\n".join(f"  {m.role}: {m.content}" for m in recent)
        return f"Conversation so far:\n{lines}\n\n"

    @classmethod
    def _render_catalog(
        cls, playbooks: Sequence[Playbook], *, with_plans: bool
    ) -> str:
        blocks = []
        for playbook in playbooks:
            lines = [
                f"- playbook_id: {playbook.playbook_id}",
                f"  purpose: {playbook.name} - {cls._one_line(playbook.description)}",
            ]
            if playbook.examples:
                lines.append("  example requests:")
                lines += [f"    - {example}" for example in playbook.examples[:MAX_EXAMPLES]]
            if with_plans:
                lines.append("  plans:")
                lines += [
                    f"    - {plan.name}: {cls._one_line(plan.description)}"
                    for plan in playbook.plans
                ]
            blocks.append("\n".join(lines))
        return "\n".join(blocks)
