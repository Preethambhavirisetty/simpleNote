from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Literal, Sequence

from app.shared.prompts.prompt import get_entity_dedup_system_prompt, get_keyword_dedup_system_prompt
from app.services.ingestion.processors.chunking import TextChunk
from app.services.ingestion.processors.chunking.chunk_types import ChunkType
from app.services.ingestion.processors.keywords.extractor import extract_keywords
from app.services.ingestion.processors.keywords.terms import prune_keywords
from app.services.ingestion.processors.text_normalization import (
    augment_markdown_table,
    normalize_text_for_keyword_extraction,
)
from app.shared.llm import llm_call_general
from app.shared.utils import build_llm_messages


TOP_N_KEYWORDS_PER_CHUNK = 15
MAX_GLOBAL_KEYWORD_CANDIDATES = 40
MAX_TOP_KEYWORDS = 15
TermKind = Literal["kw", "ent"]

log = logging.getLogger(__name__)

NON_TEXT_TERM_TYPES = {
    ChunkType.HEADING_ONLY.value,
    ChunkType.CODE.value,
    ChunkType.JSON.value,
}


@dataclass(frozen=True)
class RankedCandidate:
    term: str
    chunk_frequency: int
    occurrences: int
    specificity: int


@dataclass(frozen=True)
class ChunkKeywordResult:
    chunk_id: str
    content: str
    keywords: list[str]
    entities: list[str]
    chunk_type: str = ChunkType.CONTENT.value
    metadata: dict[str, Any] = field(default_factory=dict)
    chunk_index: int = 0
    total_chunks: int = 0


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
        skipped_count = 0

        for index, chunk in enumerate(chunks):
            chunk_id, content, chunk_type, metadata = self._chunk_data(chunk, index)
            extraction_text = self._extraction_text(content, chunk_type, metadata)
            if self._should_extract_terms(extraction_text, chunk_type, metadata):
                keywords, entities = extract_keywords(extraction_text, self.top_n_per_chunk)
            else:
                keywords, entities = [], []
                skipped_count += 1
            chunk_results.append(
                ChunkKeywordResult(
                    chunk_id=chunk_id,
                    content=content,
                    keywords=keywords,
                    entities=entities,
                    chunk_type=chunk_type,
                    metadata=metadata,
                    chunk_index=chunk.chunk_index if isinstance(chunk, TextChunk) else index,
                    total_chunks=chunk.total_chunks if isinstance(chunk, TextChunk) else len(chunks),
                )
            )

        chunk_keywords = [self.split_conjunctions(result.keywords) for result in chunk_results]
        chunk_entities = [result.entities for result in chunk_results]
        keyword_candidates = self._rank_candidates(chunk_keywords, kind="kw")
        entity_candidates = self._rank_candidates(chunk_entities, kind="ent")
        top_keywords = self._deduplicate_candidates(keyword_candidates, kind="kw")
        top_entities = self._deduplicate_candidates(entity_candidates, kind="ent")

        if skipped_count:
            self.events.append(f"keywords skipped: {skipped_count} chunks")
        self.events.append(
            f"keywords completed: {len(top_keywords)} top keywords, {len(top_entities)} entities"
        )
        return chunk_results, top_keywords, top_entities

    @staticmethod
    def _extraction_text(content: str, chunk_type: str, metadata: dict[str, Any]) -> str:
        if chunk_type == ChunkType.TABLE.value:
            augmented = augment_markdown_table(content, metadata.get("heading_context", ""))
            return normalize_text_for_keyword_extraction(augmented or content)
        return normalize_text_for_keyword_extraction(content)

    @staticmethod
    def _should_extract_terms(text: str, chunk_type: str, metadata: dict[str, Any]) -> bool:
        return (
            not metadata.get("skip_keywords", False)
            and chunk_type not in NON_TEXT_TERM_TYPES
            and any(char.isalpha() for char in text)
        )

    def _rank_candidates(
        self,
        term_groups: Sequence[Sequence[str]],
        kind: TermKind,
    ) -> list[RankedCandidate]:
        display_by_key: dict[str, str] = {}
        occurrences: Counter[str] = Counter()
        chunk_frequency: Counter[str] = Counter()

        for terms in term_groups:
            seen_in_chunk = set()
            for term in terms:
                if not isinstance(term, str) or not term.strip():
                    continue
                term = term.strip()
                key = term.lower()
                display_by_key.setdefault(key, term)
                occurrences[key] += 1
                seen_in_chunk.add(key)
            chunk_frequency.update(seen_in_chunk)

        candidates = [
            RankedCandidate(
                term=display_by_key[key],
                chunk_frequency=chunk_frequency[key],
                occurrences=occurrences[key],
                specificity=len(display_by_key[key].split()),
            )
            for key in display_by_key
            if kind == "ent" or chunk_frequency[key] >= 2 or len(display_by_key[key].split()) >= 2
        ]
        candidates.sort(
            key=lambda candidate: (
                -candidate.chunk_frequency,
                -candidate.specificity,
                -candidate.occurrences,
                -len(candidate.term),
                candidate.term.lower(),
            )
        )

        if kind == "kw":
            selected_terms = set(prune_keywords([candidate.term for candidate in candidates]))
            candidates = [candidate for candidate in candidates if candidate.term in selected_terms]
        return candidates[: self.max_global_candidates]

    @staticmethod
    def _chunk_data(chunk: TextChunk | str, index: int) -> tuple[str, str, str, dict[str, Any]]:
        if isinstance(chunk, TextChunk):
            return chunk.chunk_id, chunk.content, chunk.chunk_type, dict(chunk.metadata)
        return str(index), chunk, ChunkType.CONTENT.value, {}

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

    def deduplicate_keywords(self, keywords: Sequence[str], kind: TermKind = "kw") -> list[str]:
        candidates = self._rank_candidates([[keyword] for keyword in keywords], kind)
        return self._deduplicate_candidates(candidates, kind)

    def _deduplicate_candidates(
        self, candidates: Sequence[RankedCandidate], kind: TermKind
    ) -> list[str]:
        ranked_terms = [candidate.term for candidate in candidates]
        if not self.use_llm_dedup:
            self.events.append(f"{self._kind_label(kind)} dedup completed: local")
            return ranked_terms[: self.max_top_keywords]
        return self.deduplicate_keywords_llm(list(candidates), kind)

    def deduplicate_keywords_llm(
        self, candidates: list[RankedCandidate], kind: TermKind
    ) -> list[str]:
        if not candidates:
            return []

        ranked_terms = [candidate.term for candidate in candidates]
        allowed_keywords = {term.lower(): term for term in ranked_terms}
        keyword_text = "\n".join(
            f"term: {candidate.term} | chunk_frequency: {candidate.chunk_frequency} | "
            f"occurrences: {candidate.occurrences} | specificity: {candidate.specificity}"
            for candidate in candidates
        )
        try:
            label = self._kind_label(kind)
            self.events.append(f"{label} dedup api call")
            self.api_calls += 1
            prompt = get_keyword_dedup_system_prompt() if kind == "kw" else get_entity_dedup_system_prompt()
            result = llm_call_general(build_llm_messages(prompt, keyword_text))
            parsed_keywords = self._parse_llm_keyword_lines(result, allowed_keywords)
            self.events.append(f"{label} dedup completed: llm")
            return self._fill_keywords(parsed_keywords, ranked_terms)
        except Exception:
            log.warning("%s LLM dedup failed; using local dedup.", self._kind_label(kind), exc_info=True)
            self.events.append(f"{self._kind_label(kind)} dedup failed: using local fallback")

        return ranked_terms[: self.max_top_keywords]

    @staticmethod
    def _kind_label(kind: TermKind) -> str:
        return "keyword" if kind == "kw" else "entity"

    def split_conjunctions(self, keywords: Sequence[str]) -> list[str]:
        result = []
        for keyword in keywords:
            if not isinstance(keyword, str):
                continue
            parts = re.split(r'\s+or\s+|\s+and\s+', keyword)
            result.extend(part.strip() for part in parts if part.strip())
        return list(dict.fromkeys(result))  # dedup preserving order
