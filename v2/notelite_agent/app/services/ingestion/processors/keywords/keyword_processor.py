from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass
from typing import Literal, Sequence

from app.services.ingestion.processors.chunking import TextChunk
from app.services.ingestion.processors.keywords.extractor import extract_keywords
from app.services.ingestion.processors.keywords.terms import prune_keywords
from app.shared.llm import llm_call_general
from app.shared.utils import build_llm_messages


TOP_N_KEYWORDS_PER_CHUNK = 15
MAX_GLOBAL_KEYWORD_CANDIDATES = 40
MAX_TOP_KEYWORDS = 15
TermKind = Literal["kw", "ent"]

KEYWORD_DEDUP_SYSTEM_PROMPT = (
    "You are a keyword deduplication assistant. "
    "Given a list of keywords and phrases extracted from a document, "
    "return the most meaningful and unique terms.\n\n"
    "Rules:\n"
    "- Preserve multi-word phrases exactly as given\n"
    "- Do not split phrases into individual words\n"
    "- Do not add any terms not present in the input list\n"
    "- Remove exact duplicates and near-duplicates, keeping the most specific form\n"
    "- Remove generic single words that carry no standalone retrieval value "
    "(examples: app, set, user, results, chain, cost, tool, type, value, item, thing)\n"
    "- Remove time expressions and calendar references "
    "(examples: Monday, this week, afternoon meeting, yesterday, last month)\n"
    "- Remove sentence fragments and prepositional phrases without a clear subject "
    "(examples: instance for auth, risk of context, based on results)\n"
    "- Prefer specific named concepts, activities, decisions, and domain terms "
    "over generic objects or vague descriptors\n"
    "- Return up to 15 terms, one per line\n"
    "- No numbering, no bullets, no explanations, no preamble\n"
    "- Start directly with the first term"
    "- Do not extract physical household objects with no conceptual value"
    "(examples: cardboard boxes, coffee crystals, car seats, bedroom window)"
    "- Do not extract time expressions or calendar references"
    "(examples: Saturday afternoon, this week, afternoon meeting)"
    "- Prefer named activities, life events, decisions, relationships, "
    "and domain-specific concepts"
)

ENTITY_DEDUP_SYSTEM_PROMPT = (
    "You are a named entity validation and deduplication assistant. "
    "Given a list of candidate named entities extracted from a document, "
    "return only the valid named entities.\n\n"
    "A valid named entity is one of:\n"
    "- Person name (real individual, first or full name)\n"
    "- Product, tool, technology, or software name\n"
    "- Organization or company name\n"
    "- Specific named location, place, or geographic feature\n"
    "- Named framework, library, protocol, or standard\n"
    "- Named algorithm, method, or well-known concept\n"
    "- Named creative work (book, film, article title)\n\n"
    "Rules:\n"
    "- Remove adjectives and demonyms mistakenly tagged as entities "
    "(examples: Italian, Romanian, Northern, Ancient)\n"
    "- Remove common nouns, generic words, and document structure artifacts "
    "(examples: node, thread, entry, journal, note, section, chapter)\n"
    "- Remove conjunctions of multiple entities — split them into separate entries "
    "(example: 'X and Y' becomes two entries: X, Y)\n"
    "- Remove duplicates, keeping the most complete form "
    "(example: prefer the full name over a partial one)\n"
    "- Do not add entities not present in the input list\n"
    "- Return up to 15 valid entities, one per line\n"
    "- No numbering, no bullets, no explanations, no preamble\n"
    "- Start directly with the first entity"
)

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
        flattened_entities = [entity for entities in chunk_entities for entity in entities]
        cleaned_keywords = self.split_conjunctions(flattened_keywords)
        top_keywords = self.deduplicate_keywords(cleaned_keywords, kind="kw")
        top_entities = self.deduplicate_keywords(flattened_entities, kind="ent")

        self.events.append(
            f"keywords completed: {len(top_keywords)} top keywords, {len(top_entities)} entities"
        )
        return chunk_results, top_keywords, top_entities

    def _rank_keyword_candidates(self, keywords: Sequence[str]) -> list[str]:
        display_by_key = {}
        counter = Counter()
        for keyword in keywords:
            if not isinstance(keyword, str) or not keyword.strip():
                continue
            keyword = keyword.strip()
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

    def _rank_entity_candidates(self, entities: Sequence[str]) -> list[str]:
        display_by_key = {}
        first_seen = {}
        counter = Counter()

        for index, entity in enumerate(entities):
            if not isinstance(entity, str):
                continue
            entity = entity.strip()
            if not entity or not any(char.isalpha() for char in entity):
                continue
            key = entity.lower()
            display_by_key.setdefault(key, entity)
            first_seen.setdefault(key, index)
            counter[key] += 1

        ranked = sorted(
            display_by_key,
            key=lambda key: (-counter[key], first_seen[key]),
        )
        return [display_by_key[key] for key in ranked[: self.max_global_candidates]]

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

    def deduplicate_keywords(self, keywords: Sequence[str], kind: TermKind = "kw") -> list[str]:
        local_keywords = (
            self._rank_keyword_candidates(keywords)
            if kind == "kw"
            else self._rank_entity_candidates(keywords)
        )
        if not self.use_llm_dedup:
            self.events.append(f"{self._kind_label(kind)} dedup completed: local")
            return local_keywords[: self.max_top_keywords]
        return self.deduplicate_keywords_llm(local_keywords, kind)

    def deduplicate_keywords_llm(self, keywords: list[str], kind: TermKind) -> list[str]:
        if not keywords:
            return []

        allowed_keywords = {keyword.lower(): keyword for keyword in keywords}
        keyword_text = ", ".join(keywords)
        try:
            label = self._kind_label(kind)
            self.events.append(f"{label} dedup api call")
            self.api_calls += 1
            if kind == "kw":
                messages = build_llm_messages(KEYWORD_DEDUP_SYSTEM_PROMPT, keyword_text)
            else:
                messages = build_llm_messages(KEYWORD_DEDUP_SYSTEM_PROMPT, keyword_text)
            result = llm_call_general(messages)
            parsed_keywords = self._parse_llm_keyword_lines(result, allowed_keywords)
            self.events.append(f"{label} dedup completed: llm")
            return self._fill_keywords(parsed_keywords, keywords)
        except Exception:
            log.warning("%s LLM dedup failed; using local dedup.", self._kind_label(kind), exc_info=True)
            self.events.append(f"{self._kind_label(kind)} dedup failed: using local fallback")

        return keywords[: self.max_top_keywords]

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
