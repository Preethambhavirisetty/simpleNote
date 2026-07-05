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
        seen: set[tuple[str, datetime, str]] = set()

        for chunk in chunks:
            for entity in self.nlp(chunk.content).ents:
                if entity.label_ != "DATE":
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

        self.events.append(f"date extraction completed: {len(results)} dates")
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
