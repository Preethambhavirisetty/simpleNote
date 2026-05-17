from __future__ import annotations

import logging
import re

from app.shared.llm import llm_call_general
from app.shared.utils import build_llm_messages

log = logging.getLogger(__name__)

QUESTION_COUNT = 5
QUESTIONS_MAX_TOKENS = 200  # 5 questions at ~40 tokens each is plenty

GENERATE_QUESTIONS_SYSTEM_PROMPT = (
    "You are a question generation assistant. "
    f"Given a summary, generate exactly {QUESTION_COUNT} questions a user might naturally ask "
    "when searching their personal notes.\n\n"
    "Include:\n"
    "  - 1 factual question about a specific detail\n"
    "  - 1 conceptual question (what, why, or how)\n"
    "  - 1 broad recall question (overall or general)\n"
    "  - 1 short keyword-style search query phrased as a question\n"
    "  - 1 follow-up question that assumes prior context\n\n"
    "Rules:\n"
    "  - Return only the questions, one per line\n"
    "  - No numbering, no bullets, no explanations\n"
    "  - Every line must end with a question mark\n"
    "  - Start your response directly with the first question"
)

BINARY_QUESTION_PATTERNS = re.compile(
    r"^(is|are|was|were|did|do|does|has|have|can|could|would|should)\s",
    re.IGNORECASE
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

        if len(questions) < QUESTION_COUNT:
            self.events.append(f"questions completed: {len(questions)} generated")
            log.warning(
                "questions generation returned fewer than expected",
                extra={"expected": QUESTION_COUNT, "got": len(questions)},
            )
        else:
            self.events.append(f"questions completed: {len(questions)} generated")

        return questions

    @staticmethod
    def _parse_questions(raw: str) -> list[str]:
        questions = []
        for line in raw.splitlines():
            clean = line.strip()
            # strip leading bullets/numbers if model ignores the rule
            clean = clean.lstrip("•-*·").strip()
            clean = re.sub(r"^\d+[.)]\s*", "", clean)
            # normalize unicode question mark
            clean = clean.replace("？", "?")
            if not clean:
                continue
            # ensure ends with question mark
            if not clean.endswith("?"):
                clean = clean.rstrip(".") + "?"
            if BINARY_QUESTION_PATTERNS.match(clean):
                continue
            questions.append(clean)

        return questions[:QUESTION_COUNT]
