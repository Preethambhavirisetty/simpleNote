from __future__ import annotations

import logging
import re

from app.shared.prompts.prompt import get_generate_questions_system_prompt
from app.shared.llm import llm_call_general
from app.shared.utils import build_llm_messages

log = logging.getLogger(__name__)

# Generate more than needed so the parser can filter low-quality ones and
# still return the full target count.
_GENERATE_COUNT = 8
_KEEP_COUNT = 5

# 8 questions × ~45 tokens each, with some headroom
QUESTIONS_MAX_TOKENS = 380

BINARY_QUESTION_PATTERNS = re.compile(
    r"^(is|are|was|were|did|do|does|has|have|can|could|would|should)\s",
    re.IGNORECASE,
)


class QuestionsGenerator:

    def __init__(self):
        self.api_calls = 0
        self.events: list[str] = []

    def process(self, overall_summary: str) -> list[str]:
        self.api_calls = 0
        self.events = ["questions started"]

        if not overall_summary or not overall_summary.strip():
            self.events.append("questions skipped: empty summary")
            log.debug("questions skipped: empty summary")
            return []

        try:
            self.events.append("questions api call")
            self.api_calls += 1
            raw = llm_call_general(
                build_llm_messages(get_generate_questions_system_prompt(_GENERATE_COUNT), overall_summary),
                max_tokens=QUESTIONS_MAX_TOKENS,
                temperature=0.3,
            )
        except Exception:
            log.warning("questions generation failed", exc_info=True)
            self.events.append("questions failed")
            return []

        questions = self._parse_questions(raw)
        self.events.append(
            f"questions completed: {len(questions)} kept from {_GENERATE_COUNT} generated"
        )

        if len(questions) < _KEEP_COUNT:
            log.warning(
                "questions generation returned fewer than target after filtering",
                extra={"target": _KEEP_COUNT, "got": len(questions)},
            )

        return questions

    @staticmethod
    def _parse_questions(raw: str) -> list[str]:
        questions = []
        for line in raw.splitlines():
            clean = line.strip()
            clean = clean.lstrip("•-*·").strip()
            clean = re.sub(r"^\d+[.)]\s*", "", clean)
            clean = clean.replace("？", "?")
            if not clean:
                continue
            if not clean.endswith("?"):
                clean = clean.rstrip(".") + "?"
            if BINARY_QUESTION_PATTERNS.match(clean):
                continue
            questions.append(clean)

        return questions[:_KEEP_COUNT]
