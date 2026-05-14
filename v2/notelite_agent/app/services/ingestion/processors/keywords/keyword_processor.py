from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Sequence

from app.services.ingestion.processors.chunking import TextChunk
from app.services.ingestion.processors.keywords.extractor import extract_keywords
from app.services.ingestion.processors.keywords.terms import prune_keywords


TOP_N_KEYWORDS_PER_CHUNK = 15
MAX_GLOBAL_KEYWORD_CANDIDATES = 40
MAX_TOP_KEYWORDS = 15


@dataclass(frozen=True)
class ChunkKeywordResult:
    chunk_id: str
    keywords: list[str]
    entities: list[str]


@dataclass(frozen=True)
class KeywordProcessingResult:
    chunk_results: list[ChunkKeywordResult]
    chunk_keywords: list[list[str]]
    chunk_entities: list[list[str]]
    flattened_keywords: list[str]
    top_keywords: list[str]
    entities: list[str]


class KeywordProcessor:
    """Extract per-chunk keywords/entities and aggregate document-level terms."""

    def __init__(
        self,
        top_n_per_chunk: int = TOP_N_KEYWORDS_PER_CHUNK,
        max_global_candidates: int = MAX_GLOBAL_KEYWORD_CANDIDATES,
        max_top_keywords: int = MAX_TOP_KEYWORDS,
    ):
        self.top_n_per_chunk = top_n_per_chunk
        self.max_global_candidates = max_global_candidates
        self.max_top_keywords = max_top_keywords

    def process(self, chunks: Sequence[TextChunk | str]) -> KeywordProcessingResult:
        chunk_results = []

        for index, chunk in enumerate(chunks):
            chunk_id, content = self._chunk_data(chunk, index)
            keywords, entities = extract_keywords(content, self.top_n_per_chunk)
            chunk_results.append(
                ChunkKeywordResult(
                    chunk_id=chunk_id,
                    keywords=keywords,
                    entities=entities,
                )
            )

        chunk_keywords = [result.keywords for result in chunk_results]
        chunk_entities = [result.entities for result in chunk_results]
        flattened_keywords = [keyword for keywords in chunk_keywords for keyword in keywords]

        return KeywordProcessingResult(
            chunk_results=chunk_results,
            chunk_keywords=chunk_keywords,
            chunk_entities=chunk_entities,
            flattened_keywords=flattened_keywords,
            top_keywords=self._dedupe_keywords(flattened_keywords),
            entities=self._dedupe_entities(chunk_entities),
        )

    def _dedupe_keywords(self, keywords: list[str]) -> list[str]:
        counter = Counter(keywords)
        filtered = [
            (keyword, count)
            for keyword, count in counter.items()
            if count >= 2 or len(keyword.split()) >= 2
        ]
        ranked = [
            keyword
            for keyword, _count in sorted(
                filtered,
                key=lambda item: (-item[1], item[0]),
            )[: self.max_global_candidates]
        ]
        return prune_keywords(ranked)[: self.max_top_keywords]

    @staticmethod
    def _dedupe_entities(chunk_entities: list[list[str]]) -> list[str]:
        return list(dict.fromkeys(entity for entities in chunk_entities for entity in entities))

    @staticmethod
    def _chunk_data(chunk: TextChunk | str, index: int) -> tuple[str, str]:
        if isinstance(chunk, TextChunk):
            return chunk.chunk_id, chunk.content
        return str(index), chunk
