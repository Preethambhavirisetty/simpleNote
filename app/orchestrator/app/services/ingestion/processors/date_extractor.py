from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import dateparser
import spacy

from app.services.ingestion.processors.ingest.models import IndexChunk


_RELATIVE_DATE_PATTERN = re.compile(
    r"\b(last|next|this|ago|yesterday|today|tomorrow)\b",
    re.IGNORECASE,
)

# spaCy labels a bare number in a list ("37. Practise daily") as a DATE, and
# dateparser turns "37" into the year 2037 by filling in today's month and day.
# A numbered list therefore produced one bogus content date per item. Nothing
# downstream can tell those from real ones, so they are rejected here.
_BARE_NUMBER = re.compile(r"^\d{1,3}$")
_BARE_ORDINAL = re.compile(r"^\d{1,2}(st|nd|rd|th)$", re.IGNORECASE)
_FOUR_DIGIT_YEAR = re.compile(r"^\d{4}$")
_HAS_LETTERS = re.compile(r"[A-Za-z]")
# 2025-01-02, 3/4/25, 12.03.2024 - digits joined by a date separator.
_SEPARATED_DIGITS = re.compile(r"\d[/.\-]\d")


def is_usable_date_text(text: str) -> bool:
    """Whether a DATE entity is specific enough to store as a content date.

    Rejects text that only *parses* as a date because dateparser fills in the
    missing parts from today. "37" and "3rd" resolve to a real timestamp while
    saying nothing about when anything happened; "March 3rd", "2025", "last
    week" and "12/03/2024" all carry a real signal.
    """
    clean = text.strip()
    if not clean:
        return False
    if _BARE_ORDINAL.match(clean):
        return False
    if _FOUR_DIGIT_YEAR.match(clean):
        # A plausible year is a real signal; 3021 or 0042 is a list number.
        return 1900 <= int(clean) <= 2100
    if _BARE_NUMBER.match(clean):
        return False
    return bool(_HAS_LETTERS.search(clean) or _SEPARATED_DIGITS.search(clean))


class DateExtractor:
    """Extract normalized content dates independently from search entities."""

    def __init__(self):
        self.nlp = spacy.load("en_core_web_sm")
        self.events: list[str] = []

    def extract(
        self,
        chunks: Sequence[IndexChunk],
        created_at: datetime,
        user_timezone: str,
    ) -> list[dict]:
        """Return every unique DATE entity normalized to UTC."""
        timezone_info = self._timezone(user_timezone)
        relative_base = created_at.astimezone(timezone_info)
        results: list[dict] = []
        rejected = 0
        seen: set[tuple[str, datetime, str]] = set()

        for chunk in chunks:
            for entity in self.nlp(chunk.content).ents:
                if entity.label_ != "DATE":
                    continue
                if not is_usable_date_text(entity.text):
                    rejected += 1
                    continue

                parsed = dateparser.parse(
                    entity.text,
                    settings={
                        "RELATIVE_BASE": relative_base,
                        "TIMEZONE": str(timezone_info),
                        "RETURN_AS_TIMEZONE_AWARE": True,
                    },
                )
                if parsed is None:
                    continue

                value = parsed.astimezone(timezone.utc)
                key = (chunk.chunk_id, value, entity.text)
                if key in seen:
                    continue

                seen.add(key)
                results.append({
                    "chunk_id": chunk.chunk_id,
                    "date_value": value,
                    "date_text": entity.text,
                    "date_precision": self._precision(entity.text),
                    "date_type": "relative" if _RELATIVE_DATE_PATTERN.search(entity.text) else "absolute",
                })

        self.events.append(
            f"date extraction completed: {len(results)} dates"
            + (f", {rejected} non-dates rejected" if rejected else "")
        )
        return results

    def _timezone(self, name: str) -> ZoneInfo:
        try:
            return ZoneInfo(name)
        except Exception:
            self.events.append("date extraction timezone fallback: UTC")
            return ZoneInfo("UTC")

    @staticmethod
    def _precision(text: str) -> str:
        if re.search(r"\d{1,2}:\d{2}", text):
            return "time"
        if re.search(r"\b\d{1,2}\b", text):
            return "day"
        if re.search(r"\b\d{4}\b", text):
            return "year"
        return "month"
