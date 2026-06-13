from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Literal, Sequence

from app.core.config import (
    KEYWORD_EXTRACTION_CONCURRENCY,
    KEYWORD_EXTRACTION_MAX_CHUNKS,
    KEYWORD_EXTRACTION_MAX_TOKENS,
)
from app.shared.prompts.prompt import (
    get_entity_dedup_system_prompt,
    get_keyword_dedup_system_prompt,
    get_keyword_extraction_system_prompt,
)
from app.services.ingestion.processors.chunking import TextChunk
from app.services.ingestion.processors.chunking.chunk_types import ChunkType
from app.services.ingestion.processors.keywords.entity_extractor import extract_entity_mentions_batch
from app.services.ingestion.processors.keywords.keyword_batcher import (
    KeywordBatchItem,
    KeywordBatchResult,
    extract_keywords_batched,
)
from app.services.ingestion.processors.keywords.terms import prune_keywords
from app.services.ingestion.processors.text_normalization import (
    markdown_table_headers,
    normalize_text_for_keyword_extraction,
    without_markdown_heading_lines,
)
from app.shared.llm import llm_call_general
from app.shared.utils import build_llm_messages


TOP_N_KEYWORDS_PER_CHUNK = 10
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
    labels: tuple[str, ...] = ()
    contexts: tuple[str, ...] = ()


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
        self.api_call_counts: dict[str, int] = {
            "keyword_extraction": 0,
            "keyword_extraction_retries": 0,
            "keyword_dedup": 0,
            "entity_dedup": 0,
        }
        self.events: list[str] = []

    def process(self, chunks: Sequence[TextChunk | str]) -> tuple[list[ChunkKeywordResult], list[str], list[str]]:
        self.api_calls = 0
        self.api_call_counts = {
            "keyword_extraction": 0,
            "keyword_extraction_retries": 0,
            "keyword_dedup": 0,
            "entity_dedup": 0,
        }
        self.events = [f"keywords started: {len(chunks)} chunks"]
        prepared_chunks = []
        keyword_items = []
        entities_by_chunk: dict[str, list[str]] = {}
        entity_items: list[tuple[str, str, str, str]] = []
        entity_evidence: dict[str, dict[str, set[str] | list[str]]] = {}

        for index, chunk in enumerate(chunks):
            chunk_id, content, chunk_type, metadata = self._chunk_data(chunk, index)
            extraction_text = self._extraction_text(content, chunk_type, metadata)
            entities_by_chunk[chunk_id] = []
            if self._should_extract_entities(extraction_text, chunk_type):
                entity_items.append((
                    chunk_id,
                    without_markdown_heading_lines(extraction_text),
                    content,
                    chunk_type,
                ))

            skip_reason = self._term_skip_reason(extraction_text, chunk_type, metadata)
            if skip_reason:
                self.events.append(f"keywords extraction skipped: chunk={chunk_id} reason={skip_reason}")
            else:
                keyword_items.append(
                    KeywordBatchItem(
                        chunk_id=chunk_id,
                        chunk_type=chunk_type,
                        text=self._keyword_extraction_text(content, extraction_text, metadata),
                    )
                )
            prepared_chunks.append((chunk, index, chunk_id, content, chunk_type, metadata))

        entity_results = extract_entity_mentions_batch(
            [text for _chunk_id, text, _content, _type in entity_items]
        )
        for (chunk_id, text, content, chunk_type), mentions in zip(entity_items, entity_results):
            mentions = self._filter_table_header_mentions(mentions, content, chunk_type)
            entities_by_chunk[chunk_id] = [mention.text for mention in mentions]
            for mention in mentions:
                key = mention.text.lower()
                evidence = entity_evidence.setdefault(key, {"labels": set(), "contexts": []})
                evidence["labels"].add(mention.label)
                context = self._entity_context(text, mention.text)
                if context and context not in evidence["contexts"] and len(evidence["contexts"]) < 2:
                    evidence["contexts"].append(context)
        self.events.append(f"entity extraction completed: {len(entity_items)} chunks")
        try:
            keyword_result = extract_keywords_batched(
                keyword_items,
                system_prompt=get_keyword_extraction_system_prompt(),
                max_chunks=KEYWORD_EXTRACTION_MAX_CHUNKS,
                max_tokens=KEYWORD_EXTRACTION_MAX_TOKENS,
                concurrency=KEYWORD_EXTRACTION_CONCURRENCY,
                keywords_per_chunk=self.top_n_per_chunk,
            )
        except Exception as exc:
            log.warning("keyword extraction setup failed", exc_info=True)
            keyword_result = KeywordBatchResult(
                keywords_by_chunk={item.chunk_id: [] for item in keyword_items},
                api_calls=0,
                retries=0,
                events=[f"keyword extraction failed: {type(exc).__name__}"],
            )
        self.events.extend(keyword_result.events)
        self.api_call_counts["keyword_extraction"] = keyword_result.api_calls
        self.api_call_counts["keyword_extraction_retries"] = keyword_result.retries

        chunk_results = []
        for chunk, index, chunk_id, content, chunk_type, metadata in prepared_chunks:
            keywords = self._filter_table_header_terms(
                keyword_result.keywords_by_chunk.get(chunk_id, []),
                content,
                chunk_type,
            )
            chunk_results.append(
                ChunkKeywordResult(
                    chunk_id=chunk_id,
                    content=content,
                    keywords=keywords,
                    entities=entities_by_chunk.get(chunk_id, []),
                    chunk_type=chunk_type,
                    metadata=metadata,
                    chunk_index=chunk.chunk_index if isinstance(chunk, TextChunk) else index,
                    total_chunks=chunk.total_chunks if isinstance(chunk, TextChunk) else len(chunks),
                )
            )

        self.events.append(
            f"keyword extraction completed: eligible={len(keyword_items)} "
            f"with_keywords={sum(bool(result.keywords) for result in chunk_results)}"
        )
        chunk_keywords = [result.keywords for result in chunk_results]
        chunk_entities = [result.entities for result in chunk_results]
        section_keys = [
            result.metadata.get("heading_context") or f"chunk:{result.chunk_id}"
            for result in chunk_results
        ]
        keyword_candidates = self._rank_candidates(
            chunk_keywords, kind="kw", group_keys=section_keys
        )
        entity_candidates = self._rank_candidates(
            chunk_entities, kind="ent", evidence=entity_evidence
        )
        self.events.append(f"keyword candidates ranked: {len(keyword_candidates)}")
        self.events.append(f"entity candidates ranked: {len(entity_candidates)}")
        top_keywords = self._deduplicate_candidates(keyword_candidates, kind="kw")
        top_entities = self._deduplicate_candidates(entity_candidates, kind="ent")

        self.events.append(
            f"keywords completed: {len(top_keywords)} top keywords, {len(top_entities)} entities"
        )
        self.api_calls = sum(
            count
            for key, count in self.api_call_counts.items()
            if key != "keyword_extraction_retries"
        )
        return chunk_results, top_keywords, top_entities

    @staticmethod
    def _extraction_text(content: str, chunk_type: str, metadata: dict[str, Any]) -> str:
        return normalize_text_for_keyword_extraction(content)

    @staticmethod
    def _keyword_extraction_text(
        content: str,
        normalized_content: str,
        metadata: dict[str, Any],
    ) -> str:
        if content.strip().startswith("#"):
            return normalized_content
        heading_context = metadata.get("heading_context", "")
        if not heading_context or not metadata.get("has_heading_context"):
            return normalized_content
        return f"{heading_context}\n\n{normalized_content}".strip()

    @staticmethod
    def _should_extract_entities(text: str, chunk_type: str) -> bool:
        return chunk_type not in NON_TEXT_TERM_TYPES and any(char.isalpha() for char in text)

    @staticmethod
    def _entity_context(text: str, entity: str, radius: int = 100) -> str:
        lowered = text.lower()
        position = lowered.find(entity.lower())
        if position < 0:
            return text[: radius * 2].replace("\n", " ").strip()
        start = max(0, position - radius)
        end = min(len(text), position + len(entity) + radius)
        return text[start:end].replace("\n", " ").strip()

    @staticmethod
    def _filter_table_header_terms(
        terms: Sequence[str],
        content: str,
        chunk_type: str,
    ) -> list[str]:
        if chunk_type != ChunkType.TABLE.value:
            return list(terms)
        headers = {header.casefold() for header in markdown_table_headers(content)}
        return [term for term in terms if term.casefold() not in headers]

    @staticmethod
    def _filter_table_header_mentions(mentions, content: str, chunk_type: str):
        if chunk_type != ChunkType.TABLE.value:
            return mentions
        headers = {header.casefold() for header in markdown_table_headers(content)}
        return [mention for mention in mentions if mention.text.casefold() not in headers]

    @staticmethod
    def _term_skip_reason(text: str, chunk_type: str, metadata: dict[str, Any]) -> str:
        if metadata.get("skip_keywords", False):
            reason = metadata.get("skip_keywords_reason") or "quality_flag"
            return f"quality:{reason}"
        if chunk_type in NON_TEXT_TERM_TYPES:
            return f"structural:{chunk_type}"
        if not any(char.isalpha() for char in text):
            return "non_lexical"
        return ""

    def _rank_candidates(
        self,
        term_groups: Sequence[Sequence[str]],
        kind: TermKind,
        group_keys: Sequence[str] | None = None,
        evidence: dict[str, dict[str, set[str] | list[str]]] | None = None,
    ) -> list[RankedCandidate]:
        display_by_key: dict[str, str] = {}
        occurrences: Counter[str] = Counter()
        chunk_frequency: Counter[str] = Counter()
        terms_by_group: dict[str, set[str]] = {}
        group_keys = group_keys or [f"chunk:{index}" for index in range(len(term_groups))]

        for group_key, terms in zip(group_keys, term_groups):
            seen_in_chunk = set()
            for term in terms:
                if not isinstance(term, str) or not term.strip():
                    continue
                term = term.strip()
                key = term.lower()
                display_by_key.setdefault(key, term)
                occurrences[key] += 1
                seen_in_chunk.add(key)
            terms_by_group.setdefault(group_key, set()).update(seen_in_chunk)

        for terms in terms_by_group.values():
            chunk_frequency.update(terms)

        evidence = evidence or {}
        candidates = [
            RankedCandidate(
                term=display_by_key[key],
                chunk_frequency=chunk_frequency[key],
                occurrences=occurrences[key],
                specificity=len(display_by_key[key].split()),
                labels=tuple(sorted(evidence.get(key, {}).get("labels", set()))),
                contexts=tuple(evidence.get(key, {}).get("contexts", [])),
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

    def deduplicate_keywords(self, keywords: Sequence[str], kind: TermKind = "kw") -> list[str]:
        candidates = self._rank_candidates([[keyword] for keyword in keywords], kind)
        return self._deduplicate_candidates(candidates, kind)

    def _deduplicate_candidates(
        self, candidates: Sequence[RankedCandidate], kind: TermKind
    ) -> list[str]:
        ranked_terms = [candidate.term for candidate in candidates]
        if not self.use_llm_dedup:
            self.events.append(f"{self._kind_label(kind)} dedup completed: local")
            selected = ranked_terms[: self.max_top_keywords]
            return self._postprocess_entity_selection(selected, candidates) if kind == "ent" else selected
        return self.deduplicate_keywords_llm(list(candidates), kind)

    def deduplicate_keywords_llm(
        self, candidates: list[RankedCandidate], kind: TermKind
    ) -> list[str]:
        if not candidates:
            return []

        ranked_terms = [candidate.term for candidate in candidates]
        allowed_keywords = {term.lower(): term for term in ranked_terms}
        keyword_text = "\n".join(
            self._candidate_prompt_line(candidate, kind)
            for candidate in candidates
        )
        try:
            label = self._kind_label(kind)
            self.events.append(f"{label} dedup api call: {len(candidates)} ranked candidates")
            self.api_calls += 1
            self.api_call_counts[f"{label}_dedup"] += 1
            prompt = get_keyword_dedup_system_prompt() if kind == "kw" else get_entity_dedup_system_prompt()
            result = llm_call_general(build_llm_messages(prompt, keyword_text))
            parsed_keywords = self._parse_llm_keyword_lines(result, allowed_keywords)
            selected = parsed_keywords[: self.max_top_keywords]
            if kind == "ent":
                selected = self._postprocess_entity_selection(selected, candidates)
            self.events.append(
                f"{label} dedup completed: llm selected={len(selected)} "
                f"rejected={len(candidates) - len(selected)}"
            )
            return selected
        except Exception:
            log.warning("%s LLM dedup failed; using local dedup.", self._kind_label(kind), exc_info=True)
            self.events.append(f"{self._kind_label(kind)} dedup failed: using local fallback")

        selected = ranked_terms[: self.max_top_keywords]
        return self._postprocess_entity_selection(selected, candidates) if kind == "ent" else selected

    @staticmethod
    def _postprocess_entity_selection(
        selected: Sequence[str],
        candidates: Sequence[RankedCandidate],
    ) -> list[str]:
        person_candidates = [
            candidate.term
            for candidate in candidates
            if "PERSON" in candidate.labels
        ]
        person_by_key = {candidate.lower(): candidate for candidate in person_candidates}
        output = []
        seen = set()

        for term in selected:
            key = term.lower()
            if key in person_by_key:
                token_set = KeywordProcessor._entity_name_tokens(term)
                supersets = [
                    candidate
                    for candidate in person_candidates
                    if token_set < KeywordProcessor._entity_name_tokens(candidate)
                ]
                if len(supersets) == 1:
                    term = supersets[0]
                    key = term.lower()
            if key not in seen:
                seen.add(key)
                output.append(term)
        return output

    @staticmethod
    def _entity_name_tokens(entity: str) -> set[str]:
        return set(re.findall(r"[a-z0-9]+", entity.lower()))

    @staticmethod
    def _candidate_prompt_line(candidate: RankedCandidate, kind: TermKind) -> str:
        frequency_label = "section_frequency" if kind == "kw" else "chunk_frequency"
        line = (
            f"term: {candidate.term} | {frequency_label}: {candidate.chunk_frequency} | "
            f"occurrences: {candidate.occurrences} | specificity: {candidate.specificity}"
        )
        if kind == "ent":
            labels = ", ".join(candidate.labels) or "unknown"
            contexts = " || ".join(candidate.contexts) or "unavailable"
            line += f" | spacy_labels: {labels} | example_context: {contexts}"
        return line

    @staticmethod
    def _kind_label(kind: TermKind) -> str:
        return "keyword" if kind == "kw" else "entity"
