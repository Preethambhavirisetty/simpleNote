from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass
from typing import Sequence

from app.services.ingestion.processors.chunking import TextChunk
from app.services.ingestion.processors.keywords.extractor import extract_keywords
from app.services.ingestion.processors.keywords.terms import prune_keywords
from app.shared.llm import llm_call_general


TOP_N_KEYWORDS_PER_CHUNK = 15
MAX_GLOBAL_KEYWORD_CANDIDATES = 40
MAX_TOP_KEYWORDS = 15

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChunkKeywordResult:
    chunk_id: str
    content: str
    keywords: list[str]
    entities: list[str]


@dataclass(frozen=True)
class KeywordProcessingResult:
    chunk_results: list[ChunkKeywordResult]
    chunk_keywords: list[list[str]]
    chunk_entities: list[list[str]]
    cleaned_keywords: list[str]
    top_keywords: list[str]
    entities: list[str]


class KeywordProcessor:
    """Extract per-chunk keywords/entities and aggregate document-level terms."""

    def __init__(
        self,
        top_n_per_chunk: int = TOP_N_KEYWORDS_PER_CHUNK,
        max_global_candidates: int = MAX_GLOBAL_KEYWORD_CANDIDATES,
        max_top_keywords: int = MAX_TOP_KEYWORDS,
        use_llm_dedup: bool = True,
    ):
        self.top_n_per_chunk = top_n_per_chunk
        self.max_global_candidates = max_global_candidates
        self.max_top_keywords = max_top_keywords
        self.use_llm_dedup = use_llm_dedup
        self.api_calls = 0
        self.events: list[str] = []

    def process(self, chunks: Sequence[TextChunk | str]) -> tuple[list[ChunkKeywordResult], list[str], list[str]]:
        self.api_calls = 0
        self.events = [f"keywords started: {len(chunks)} chunks"]
        chunk_results = []

        for index, chunk in enumerate(chunks):
            chunk_id, content = self._chunk_data(chunk, index)
            keywords, entities = extract_keywords(content, self.top_n_per_chunk)
            chunk_results.append(
                ChunkKeywordResult(
                    chunk_id=chunk_id,
                    content=content,
                    keywords=keywords,
                    entities=entities,
                )
            )

        chunk_keywords = [result.keywords for result in chunk_results]
        chunk_entities = [result.entities for result in chunk_results]
        flattened_keywords = [keyword for keywords in chunk_keywords for keyword in keywords]
        cleaned_keywords = self.split_conjunctions(flattened_keywords)
        top_keywords = self.deduplicate_keywords(cleaned_keywords)
        entities = self._dedupe_entities(chunk_entities)

        self.events.append(
            f"keywords completed: {len(top_keywords)} top keywords, {len(entities)} entities"
        )
        return chunk_results, top_keywords, entities

    def _rank_keyword_candidates(self, keywords: list[str]) -> list[str]:
        display_by_key = {}
        counter = Counter()
        for keyword in keywords:
            key = keyword.lower()
            display_by_key.setdefault(key, keyword)
            counter[key] += 1

        filtered = [
            (display_by_key[key], count)
            for key, count in counter.items()
            if count >= 2 or len(display_by_key[key].split()) >= 2
        ]
        ranked = [
            keyword
            for keyword, _count in sorted(
                filtered,
                key=lambda item: (-item[1], item[0]),
            )[: self.max_global_candidates]
        ]
        return prune_keywords(ranked)[: self.max_global_candidates]

    @staticmethod
    def _dedupe_entities(chunk_entities: list[list[str]]) -> list[str]:
        seen = set()
        deduped = []
        for entity in (entity for entities in chunk_entities for entity in entities):
            key = entity.lower()
            if key not in seen:
                seen.add(key)
                deduped.append(entity)
        return deduped

    @staticmethod
    def _chunk_data(chunk: TextChunk | str, index: int) -> tuple[str, str]:
        if isinstance(chunk, TextChunk):
            return chunk.chunk_id, chunk.content
        return str(index), chunk

    @staticmethod
    def _parse_llm_keyword_lines(
        text: str,
        allowed_keywords: dict[str, str],
    ) -> list[str]:
        keywords = []
        seen = set()
        for line in text.splitlines():
            keyword = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", line).strip()
            if not keyword:
                continue
            key = keyword.lower()
            if key not in allowed_keywords:
                continue
            if key not in seen:
                seen.add(key)
                keywords.append(allowed_keywords[key])
        return keywords

    def _fill_keywords(self, parsed_keywords: list[str], fallback_keywords: list[str]) -> list[str]:
        seen = {keyword.lower() for keyword in parsed_keywords}
        filled = list(parsed_keywords)

        for keyword in fallback_keywords:
            key = keyword.lower()
            if key in seen:
                continue
            filled.append(keyword)
            seen.add(key)
            if len(filled) >= self.max_top_keywords:
                break

        return filled[: self.max_top_keywords]

    def deduplicate_keywords(self, keywords: list[str]) -> list[str]:
        local_keywords = self._rank_keyword_candidates(keywords)
        if not self.use_llm_dedup:
            self.events.append("keyword dedup completed: local")
            return local_keywords[: self.max_top_keywords]
        return self.deduplicate_keywords_llm(local_keywords)

    def deduplicate_keywords_llm(self, keywords: list[str]) -> list[str]:
        if not keywords:
            return []

        allowed_keywords = {keyword.lower(): keyword for keyword in keywords}
        keyword_text = ", ".join(keywords)
        try:
            self.events.append("keyword dedup api call")
            self.api_calls += 1
            messages = [
                {
                    "role": "system",
                    "content": "You are a keyword deduplication assistant. Given a list of keywords and phrases from a document, return the top 15 most meaningful and unique terms from the list provided.\n\nRules:\n- Preserve multi-word phrases exactly as given\n- Do not split phrases into individual words\n- Do not add any terms that are not in the input list\n- Remove duplicates and generic single words like app, set, user, results, chain, cost, tool, web\n- Return one term per line, no numbering, no explanations\n- Start your response directly with the first term, no preamble, no header\n- Return exactly 15 terms, no more."
                },
                {"role": "user", "content": keyword_text},
            ]
            result = llm_call_general(messages)
            parsed_keywords = self._parse_llm_keyword_lines(result, allowed_keywords)
            self.events.append("keyword dedup completed: llm")
            return self._fill_keywords(parsed_keywords, keywords)
        except Exception:
            log.warning("Keyword LLM dedup failed; using local dedup.", exc_info=True)
            self.events.append("keyword dedup failed: using local fallback")

        return keywords[: self.max_top_keywords]

    def split_conjunctions(self, keywords):
        result = []
        for kw in keywords:
            parts = re.split(r'\s+or\s+|\s+and\s+', kw)
            result.extend(p.strip() for p in parts)
        return list(dict.fromkeys(result))  # dedup preserving order
