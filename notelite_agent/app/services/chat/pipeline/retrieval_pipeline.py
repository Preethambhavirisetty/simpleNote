from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from dateparser.search import search_dates
from llama_index.core import Document as LlamaDocument

from app.core.config import (
    HYDE_MAX_TOKENS,
    HYDE_TIMEOUT,
    LLM_SUMMARIZER_MODEL,
    RETRIEVAL_CHUNK_BUDGET,
    RETRIEVAL_CONTEXT_SEED_LIMIT,
    RETRIEVAL_HISTORY_BUDGET,
    RETRIEVAL_MAX_SUMMARIES,
    RETRIEVAL_NEIGHBOR_SEED_LIMIT,
    RETRIEVAL_RRF_K,
    RETRIEVAL_RRF_TOP_K,
    RETRIEVAL_RRF_WEIGHTS,
    RETRIEVAL_SEARCH_WORKERS,
    RETRIEVAL_SUMMARY_BUDGET,
)
from app.services.chat.reranker import rerank
from app.services.ingestion.storage.postgres_store import PostgresArtifactStore
from app.services.ingestion.storage.vector_store import QdrantVectorStore
from app.shared.llm import llm_call_general
from app.shared.utils import count_tokens


SearchHit = tuple[LlamaDocument, float]
SearchResults = list[SearchHit]
SearchTask = Callable[[], SearchResults]

_SHORT_FOLLOWUP_MAX_TERMS = 3
_FRAGMENT_TOKEN_THRESHOLD = 80
_MAX_HISTORY_MESSAGES = 6

_TEMPORAL_PATTERN = re.compile(
    r"\b(today|yesterday|tomorrow|last|next|this|january|february|march|april|may|"
    r"june|july|august|september|october|november|december|\d{4})\b",
    re.IGNORECASE,
)
_MONTH_PATTERN = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|october|"
    r"november|december)\b",
    re.IGNORECASE,
)
_NUMBER_PATTERN = re.compile(r"(?<!\w)\d+(?:[.,]\d+)*(?:%|\b)")


@dataclass(frozen=True)
class PreparedQuery:
    original_query: str
    search_query: str
    user_timezone: str = "UTC"
    date_start: datetime | None = None
    date_end: datetime | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class QueryEmbeddings:
    original_dense: list[float]
    original_sparse: Any
    hyde_dense: list[float] | None = None


@dataclass
class RetrievalResult:
    context_texts: list[str]
    references: list[dict[str, Any]]
    diagnostics: dict[str, Any]
    bounded_history: list[dict[str, str]]
    events: list[str] = field(default_factory=list)


def contextualize_query(
    query: str,
    history: Sequence[Mapping[str, str]] | None,
) -> str:
    """Add recent conversation context only for short follow-up queries."""
    if len(re.findall(r"\w+", query)) > _SHORT_FOLLOWUP_MAX_TERMS or not history:
        return query

    recent_messages = [
        str(message.get("content", "")).strip()
        for message in history[-2:]
        if message.get("role") in {"user", "assistant"} and message.get("content")
    ]
    return "\n".join([*recent_messages, query]) if recent_messages else query


def preprocess_query(
    query: str,
    user_id: str,
    history: Sequence[Mapping[str, str]] | None,
    postgres: PostgresArtifactStore,
) -> PreparedQuery:
    """Normalize a query and derive an optional UTC temporal range."""
    original_query = unicodedata.normalize("NFKC", query).strip()
    search_query = contextualize_query(original_query, history)
    user_timezone = postgres.user_timezone(user_id)
    date_start, date_end = _date_range(original_query, user_timezone)

    return PreparedQuery(
        original_query=original_query,
        search_query=search_query,
        user_timezone=user_timezone,
        date_start=date_start,
        date_end=date_end,
        diagnostics={
            "temporal_signal": date_start is not None,
            "language": "en",
        },
    )


def generate_hyde(prepared: PreparedQuery) -> tuple[str | None, str]:
    """Generate a hypothetical note passage, falling back cleanly on failure."""
    prompt = (
        "Write a brief note excerpt that would directly answer this question. "
        "Write as a note excerpt, not a letter. Do not include a salutation, signature, "
        "reminders, links, or unsupported details. Use concise note-like prose.\n\n"
        f"Question: {prepared.original_query}"
    )
    try:
        value = llm_call_general(
            [{"role": "user", "content": prompt}],
            model=LLM_SUMMARIZER_MODEL,
            max_tokens=HYDE_MAX_TOKENS,
            timeout=HYDE_TIMEOUT,
        ).strip()
    except Exception as exc:
        return None, f"fallback:{type(exc).__name__}"

    if not value:
        return None, "empty"
    if _invented_numbers(value, prepared.original_query):
        return None, "rejected:unsupported_numbers"
    return value, "completed"


def embed_query(
    store: QdrantVectorStore,
    prepared: PreparedQuery,
    hyde: str | None,
) -> QueryEmbeddings:
    """Embed the original query and optional HyDE passage in one request."""
    texts = [prepared.search_query]
    if hyde:
        texts.append(hyde)

    embeddings = store.embed_query_texts(texts)
    return QueryEmbeddings(
        original_dense=embeddings.dense[0],
        original_sparse=embeddings.sparse[0],
        hyde_dense=embeddings.dense[1] if hyde else None,
    )


def weighted_rrf(
    sources: Mapping[str, Sequence[SearchHit]],
    top_k: int = RETRIEVAL_RRF_TOP_K,
) -> tuple[SearchResults, dict[str, Any]]:
    """Fuse chunk result lists using configurable weighted reciprocal rank fusion."""
    scores: dict[tuple[str, str], float] = defaultdict(float)
    documents: dict[tuple[str, str], LlamaDocument] = {}
    contributions: dict[str, dict[str, float]] = defaultdict(dict)

    for source_name, hits in sources.items():
        weight = RETRIEVAL_RRF_WEIGHTS.get(source_name, 1.0)
        for rank, (document, _score) in enumerate(hits, start=1):
            identity = _document_identity(document)
            contribution = weight / (RETRIEVAL_RRF_K + rank)
            documents[identity] = document
            scores[identity] += contribution
            contributions[_identity_text(identity)][source_name] = contribution

    ranked = sorted(
        ((documents[identity], score) for identity, score in scores.items()),
        key=lambda item: item[1],
        reverse=True,
    )[:top_k]
    diagnostics = {
        "contributions": dict(contributions),
        "source_counts": {name: len(hits) for name, hits in sources.items()},
    }
    return ranked, diagnostics


def multi_collection_search(
    store: QdrantVectorStore,
    prepared: PreparedQuery,
    embeddings: QueryEmbeddings,
    metadata_filter: Mapping[str, Any] | None,
    postgres: PostgresArtifactStore,
) -> tuple[dict[str, SearchResults], dict[str, Any]]:
    """Run global searches, then document-filtered chunk searches."""
    identities = _date_identities(prepared, metadata_filter, postgres)
    date_filter_active = prepared.date_start is not None and prepared.date_end is not None
    chunk_search_allowed = not date_filter_active or bool(identities)

    global_tasks = _global_search_tasks(
        store,
        embeddings,
        metadata_filter,
        identities,
        chunk_search_allowed,
    )
    global_results, errors = _run_search_tasks(global_tasks, RETRIEVAL_SEARCH_WORKERS)

    doc_ids = []
    if not date_filter_active or identities:
        doc_ids = _document_ids(global_results.get("summary", []), global_results.get("question", []))

    sources = {
        name: hits
        for name, hits in global_results.items()
        if name.startswith("chunk_")
    }
    if doc_ids:
        filtered_tasks = _filtered_search_tasks(
            store,
            embeddings,
            metadata_filter,
            doc_ids,
            identities,
        )
        filtered_results, filtered_errors = _run_search_tasks(filtered_tasks, max_workers=2)
        sources.update(filtered_results)
        errors.update(filtered_errors)

    return sources, {
        "summary_doc_ids": doc_ids,
        "date_identity_count": len(identities or []),
        "source_errors": errors,
    }


def assemble_context(
    store: QdrantVectorStore,
    postgres: PostgresArtifactStore,
    seeds: Sequence[SearchHit],
) -> tuple[list[str], list[dict[str, Any]], dict[str, Any]]:
    """Expand seed chunks with neighbors and selectively attach summaries."""
    selected_seeds = list(seeds[:RETRIEVAL_CONTEXT_SEED_LIMIT])
    context_documents: list[LlamaDocument] = []
    seen: set[tuple[str, str]] = set()
    remaining_budget = RETRIEVAL_CHUNK_BUDGET
    neighbor_count = 0

    for index, (seed, _score) in enumerate(selected_seeds):
        documents = [seed]
        if (
            index < RETRIEVAL_NEIGHBOR_SEED_LIMIT
            and count_tokens(seed.text) < _FRAGMENT_TOKEN_THRESHOLD
        ):
            documents = _seed_with_neighbors(store, postgres, seed)

        for document in documents:
            if document is None:
                continue
            identity = _document_identity(document)
            token_count = count_tokens(document.text)
            if identity in seen or token_count > remaining_budget:
                continue
            seen.add(identity)
            context_documents.append(document)
            remaining_budget -= token_count
            if document is not seed:
                neighbor_count += 1

    ordered_context_documents = _order_context_documents(context_documents, selected_seeds)
    context_texts = [document.text for document in ordered_context_documents]
    document_ids = _document_ids(selected_seeds)
    if _should_attach_summaries(selected_seeds, document_ids):
        for summary in postgres.summaries(document_ids, RETRIEVAL_MAX_SUMMARIES):
            if count_tokens(summary) <= RETRIEVAL_SUMMARY_BUDGET:
                context_texts.append(f"Document summary:\n{summary}")

    references = _references(selected_seeds, ordered_context_documents)
    diagnostics = {
        "remaining_chunk_budget": remaining_budget,
        "expanded_context_count": len(context_texts),
        "context_seed_count": len(selected_seeds),
        "neighbor_count": neighbor_count,
    }
    return context_texts, references, diagnostics


def run_retrieval(
    store: QdrantVectorStore,
    query: str,
    user_id: str,
    k: int,
    role: str,
    history: Sequence[Mapping[str, str]] | None = None,
    postgres: PostgresArtifactStore | None = None,
) -> RetrievalResult:
    """Run the complete intent-agnostic retrieval pipeline."""
    events = ["retrieval started"]
    artifact_store = postgres or PostgresArtifactStore()

    prepared = preprocess_query(query, user_id, history, artifact_store)
    events.append(
        f"retrieval preprocess completed: temporal={prepared.date_start is not None}"
    )

    hyde, hyde_status = generate_hyde(prepared)
    events.append(f"retrieval hyde {hyde_status}")

    embeddings = embed_query(store, prepared, hyde)
    events.append(f"retrieval embedding completed: hyde={hyde is not None}")

    metadata_filter = None if role == "admin" else {"user_id": user_id}
    sources, search_diagnostics = multi_collection_search(
        store,
        prepared,
        embeddings,
        metadata_filter,
        artifact_store,
    )
    search_candidate_count = sum(len(hits) for hits in sources.values())
    events.append(
        f"retrieval search completed: sources={len(sources)} candidates={search_candidate_count}"
    )
    if search_diagnostics["source_errors"]:
        events.append(
            f"retrieval search partial failure: sources={len(search_diagnostics['source_errors'])}"
        )

    fused, rrf_diagnostics = weighted_rrf(sources)
    events.append(f"retrieval rrf completed: candidates={len(fused)}")

    seeds = rerank(prepared.original_query, fused, top_k=k)
    events.append(f"retrieval rerank completed: seeds={len(seeds)}")

    context_texts, references, context_diagnostics = assemble_context(
        store,
        artifact_store,
        seeds,
    )
    events.append(
        f"retrieval context completed: chunks={len(context_texts)} sources={len(references)}"
    )
    events.append("retrieval completed")

    return RetrievalResult(
        context_texts=context_texts,
        references=references,
        bounded_history=_bounded_history(history),
        events=events,
        diagnostics={
            "prepared": prepared.diagnostics,
            "hyde_status": hyde_status,
            "search": search_diagnostics,
            "rrf": rrf_diagnostics,
            "seed_count": len(seeds),
            "context": context_diagnostics,
        },
    )


def _date_range(query: str, user_timezone: str) -> tuple[datetime | None, datetime | None]:
    if not _TEMPORAL_PATTERN.search(query):
        return None, None

    matches = search_dates(
        query,
        settings={
            "TIMEZONE": user_timezone,
            "RETURN_AS_TIMEZONE_AWARE": True,
        },
    )
    if not matches:
        return None, None

    phrase, parsed = matches[0]
    if _MONTH_PATTERN.search(phrase) and not re.search(r"\b\d{1,2}\b", phrase):
        month_start = parsed.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
        return month_start.astimezone(timezone.utc), next_month.astimezone(timezone.utc)

    day_start = parsed.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return day_start, day_start + timedelta(days=1)


def _date_identities(
    prepared: PreparedQuery,
    metadata_filter: Mapping[str, Any] | None,
    postgres: PostgresArtifactStore,
) -> list[tuple[str, str]] | None:
    if prepared.date_start is None or prepared.date_end is None:
        return None
    user_id = str(metadata_filter["user_id"]) if metadata_filter else None
    return postgres.matching_identities(user_id, prepared.date_start, prepared.date_end)


def _global_search_tasks(
    store: QdrantVectorStore,
    embeddings: QueryEmbeddings,
    metadata_filter: Mapping[str, Any] | None,
    identities: Sequence[tuple[str, str]] | None,
    chunk_search_allowed: bool,
) -> dict[str, SearchTask]:
    tasks: dict[str, SearchTask] = {
        "chunk_dense_original": lambda: store.search_chunk_dense(
            embeddings.original_dense,
            limit=50,
            metadata_filter=metadata_filter,
            identities=identities,
        ) if chunk_search_allowed else [],
        "chunk_sparse_bm25": lambda: store.search_chunk_sparse(
            embeddings.original_sparse,
            limit=50,
            metadata_filter=metadata_filter,
            identities=identities,
        ) if chunk_search_allowed else [],
        "summary": lambda: store.search_summary_dense(
            embeddings.original_dense,
            limit=10,
            metadata_filter=metadata_filter,
        ),
        "question": lambda: store.search_question_dense(
            embeddings.original_dense,
            limit=10,
            metadata_filter=metadata_filter,
        ),
    }
    if embeddings.hyde_dense:
        tasks["chunk_dense_hyde"] = lambda: store.search_chunk_dense(
            embeddings.hyde_dense,
            limit=50,
            metadata_filter=metadata_filter,
            identities=identities,
        ) if chunk_search_allowed else []
    return tasks


def _filtered_search_tasks(
    store: QdrantVectorStore,
    embeddings: QueryEmbeddings,
    metadata_filter: Mapping[str, Any] | None,
    doc_ids: Sequence[str],
    identities: Sequence[tuple[str, str]] | None,
) -> dict[str, SearchTask]:
    return {
        "chunk_filtered_dense": lambda: store.search_chunk_dense(
            embeddings.original_dense,
            limit=50,
            metadata_filter=metadata_filter,
            doc_ids=doc_ids,
            identities=identities,
        ),
        "chunk_filtered_sparse": lambda: store.search_chunk_sparse(
            embeddings.original_sparse,
            limit=50,
            metadata_filter=metadata_filter,
            doc_ids=doc_ids,
            identities=identities,
        ),
    }


def _run_search_tasks(
    tasks: Mapping[str, SearchTask],
    max_workers: int,
) -> tuple[dict[str, SearchResults], dict[str, str]]:
    results: dict[str, SearchResults] = {}
    errors: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures: dict[str, Future[SearchResults]] = {
            name: pool.submit(task)
            for name, task in tasks.items()
        }
        for name, future in futures.items():
            try:
                results[name] = future.result()
            except Exception as exc:
                results[name] = []
                errors[name] = type(exc).__name__
    return results, errors


def _seed_with_neighbors(
    store: QdrantVectorStore,
    postgres: PostgresArtifactStore,
    seed: LlamaDocument,
) -> list[LlamaDocument | None]:
    document_id = str(seed.metadata.get("doc_id") or "")
    return [
        _neighbor(store, postgres, document_id, seed.metadata.get("prev_chunk_id")),
        seed,
        _neighbor(store, postgres, document_id, seed.metadata.get("next_chunk_id")),
    ]


def _neighbor(
    store: QdrantVectorStore,
    postgres: PostgresArtifactStore,
    document_id: str,
    chunk_id: Any,
) -> LlamaDocument | None:
    if not chunk_id:
        return None

    neighbor = store.fetch_neighbor(document_id, chunk_id)
    if neighbor is not None:
        return neighbor

    skipped = postgres.skipped_chunk(document_id, str(chunk_id))
    if skipped is None:
        return None
    return LlamaDocument(
        text=skipped.content,
        metadata={
            **skipped.metadata_json,
            "doc_id": document_id,
            "chunk_id": skipped.chunk_id,
        },
    )


def _bounded_history(history: Sequence[Mapping[str, str]] | None) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    remaining_budget = RETRIEVAL_HISTORY_BUDGET

    for message in reversed(history or []):
        content = str(message.get("content", "")).strip()
        token_count = count_tokens(content)
        if not content or token_count > remaining_budget:
            continue
        result.append({
            "role": str(message.get("role", "user")),
            "content": content,
        })
        remaining_budget -= token_count
        if len(result) == _MAX_HISTORY_MESSAGES:
            break
    return list(reversed(result))


def _references(
    seeds: Sequence[SearchHit],
    context_documents: Sequence[LlamaDocument],
) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    by_note_id: dict[str, dict[str, Any]] = {}
    seed_scores = {_document_identity(document): score for document, score in seeds}

    for document, _score in seeds:
        note_id = str(document.metadata.get("note_id") or "")
        if not note_id or note_id in by_note_id:
            continue
        reference = {
            "note_id": note_id,
            "folder_id": str(document.metadata.get("folder_id") or ""),
            "title": str(document.metadata.get("note_title") or "Untitled"),
            "folder": str(document.metadata.get("folder_title") or ""),
            "chunk_ids": [],
            "chunks": [],
        }
        references.append(reference)
        by_note_id[note_id] = reference

    for document in context_documents:
        note_id = str(document.metadata.get("note_id") or "")
        reference = by_note_id.get(note_id)
        if reference is None:
            continue
        identity = _document_identity(document)
        chunk_id = str(document.metadata.get("chunk_id") or document.id_)
        if chunk_id in reference["chunk_ids"]:
            continue
        reference["chunk_ids"].append(chunk_id)
        reference["chunks"].append({
            "chunk_id": chunk_id,
            "doc_id": str(document.metadata.get("doc_id") or ""),
            "chunk_index": document.metadata.get("chunk_index"),
            "total_chunks": document.metadata.get("total_chunks"),
            "chunk_type": str(document.metadata.get("chunk_type") or ""),
            "text": document.text,
            "is_seed": identity in seed_scores,
            "score": seed_scores.get(identity),
            "keywords": document.metadata.get("keywords") or [],
            "entities": document.metadata.get("entities") or [],
        })

    return references


def _should_attach_summaries(seeds: Sequence[SearchHit], document_ids: Sequence[str]) -> bool:
    return len(document_ids) > 1 or bool(
        seeds and count_tokens(seeds[0][0].text) < _FRAGMENT_TOKEN_THRESHOLD
    )


def _document_ids(*hit_lists: Sequence[SearchHit]) -> list[str]:
    return list(dict.fromkeys(
        str(document.metadata["doc_id"])
        for hits in hit_lists
        for document, _score in hits
        if document.metadata.get("doc_id")
    ))


def _document_identity(document: LlamaDocument) -> tuple[str, str]:
    return (
        str(document.metadata.get("doc_id", "")),
        str(document.metadata.get("chunk_id", document.id_)),
    )


def _identity_text(identity: tuple[str, str]) -> str:
    return f"{identity[0]}::{identity[1]}"


def _invented_numbers(generated_text: str, query: str) -> bool:
    query_numbers = {
        match.group(0).replace(",", "").casefold()
        for match in _NUMBER_PATTERN.finditer(query)
    }
    generated_numbers = {
        match.group(0).replace(",", "").casefold()
        for match in _NUMBER_PATTERN.finditer(generated_text)
    }
    return bool(generated_numbers - query_numbers)


def _order_context_documents(
    documents: Sequence[LlamaDocument],
    seeds: Sequence[SearchHit],
) -> list[LlamaDocument]:
    document_rank = {
        document_id: rank
        for rank, document_id in enumerate(_document_ids(seeds))
    }
    return sorted(
        documents,
        key=lambda document: (
            document_rank.get(
                str(document.metadata.get("doc_id", "")),
                len(document_rank),
            ),
            _chunk_index(document),
        ),
    )


def _chunk_index(document: LlamaDocument) -> int:
    try:
        return int(document.metadata.get("chunk_index", 0))
    except (TypeError, ValueError):
        return 0
