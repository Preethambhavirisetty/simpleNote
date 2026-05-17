from __future__ import annotations

import logging
import re

from app.shared.llm import llm_call_general
from app.shared.utils import build_llm_messages

log = logging.getLogger(__name__)

# Generate more than needed so the parser can filter low-quality ones and
# still return the full target count.
_GENERATE_COUNT = 8
_KEEP_COUNT = 5

# 8 questions × ~45 tokens each, with some headroom
QUESTIONS_MAX_TOKENS = 380

GENERATE_QUESTIONS_SYSTEM_PROMPT = (
    "You are a question generation assistant. "
    f"Given a summary, generate exactly {_GENERATE_COUNT} questions a user might naturally ask "
    "when searching their personal notes.\n\n"
    "Include:\n"
    "  - 2 factual questions about specific details\n"
    "  - 1 conceptual question (what, why, or how)\n"
    "  - 1 broad recall question (overall or general)\n"
    "  - 1 short keyword-style search query phrased as a question\n"
    "  - 1 follow-up question that assumes prior context\n"
    "  - 2 open-ended questions about decisions, tradeoffs, or next steps\n\n"
    "Rules:\n"
    "  - Return only the questions, one per line\n"
    "  - No numbering, no bullets, no explanations\n"
    "  - Every line must end with a question mark\n"
    "  - Start your response directly with the first question"
)

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
                build_llm_messages(GENERATE_QUESTIONS_SYSTEM_PROMPT, overall_summary),
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
