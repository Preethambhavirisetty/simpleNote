from __future__ import annotations

from typing import Any

from app.services.chat.pipeline.retrieval_pipeline import (
    PreparedQuery,
    QueryEmbeddings,
    embed_query,
    generate_hyde,
    multi_collection_search,
    preprocess_query,
    run_retrieval,
    weighted_rrf,
)
from app.services.chat.reranker import rerank as rerank_hits
from app.services.ingestion.storage.postgres_store import PostgresArtifactStore
from app.services.ingestion.storage.vector_store import QdrantVectorStore
from app.shared.prompts import prompt

from .schema import PromptPayload, StagePayload


class RetrievalActionServices:
    """Run retrieval stages independently for diagnostics and evaluation."""

    def __init__(self, vector_store: QdrantVectorStore):
        self.vector_store = vector_store
        self.postgres = PostgresArtifactStore()

    def preprocess(self, payload: StagePayload) -> dict[str, Any]:
        prepared = self._prepared(payload)
        return {
            "original_query": prepared.original_query,
            "search_query": prepared.search_query,
            "user_timezone": prepared.user_timezone,
            "date_start": prepared.date_start,
            "date_end": prepared.date_end,
            "diagnostics": prepared.diagnostics,
            "events": [
                f"retrieval preprocess completed: temporal={prepared.date_start is not None}"
            ],
        }

    def hyde(self, payload: StagePayload) -> dict[str, Any]:
        value, status = generate_hyde(self._prepared(payload))
        return {
            "hyde_text": value,
            "status": status,
            "events": [f"retrieval hyde {status}"],
        }

    def embed(self, payload: StagePayload) -> dict[str, Any]:
        embeddings = self._embeddings(payload)
        return {
            "original_dense_dim": len(embeddings.original_dense),
            "original_sparse_terms": len(embeddings.original_sparse.get("indices", [])),
            "hyde_dense_dim": len(embeddings.hyde_dense or []),
            "events": [
                f"retrieval embedding completed: hyde={embeddings.hyde_dense is not None}"
            ],
        }

    def search(self, payload: StagePayload) -> dict[str, Any]:
        prepared, sources, diagnostics = self._sources(payload)
        return {
            "prepared_query": prepared.search_query,
            "sources": {
                name: [self._hit(hit) for hit in hits]
                for name, hits in sources.items()
            },
            "diagnostics": diagnostics,
            "events": self._search_events(sources, diagnostics),
        }

    def rrf(self, payload: StagePayload) -> dict[str, Any]:
        _prepared, sources, _search_diagnostics = self._sources(payload)
        hits, diagnostics = weighted_rrf(sources)
        return {
            "hits": [self._hit(hit) for hit in hits],
            "diagnostics": diagnostics,
            "events": [f"retrieval rrf completed: candidates={len(hits)}"],
        }

    def rerank(self, payload: StagePayload) -> dict[str, Any]:
        prepared, sources, _search_diagnostics = self._sources(payload)
        fused_hits, rrf_diagnostics = weighted_rrf(sources)
        ranked_hits = rerank_hits(prepared.original_query, fused_hits, top_k=payload.k)
        return {
            "hits": [self._hit(hit) for hit in ranked_hits],
            "rrf_diagnostics": rrf_diagnostics,
            "events": [f"retrieval rerank completed: seeds={len(ranked_hits)}"],
        }

    def context(self, payload: StagePayload) -> dict[str, Any]:
        return self.pipeline(payload)

    def pipeline(self, payload: StagePayload) -> dict[str, Any]:
        result = run_retrieval(
            self.vector_store,
            payload.query,
            payload.user_id,
            payload.k,
            payload.role,
            self._history(payload),
            self.postgres,
        )
        return {
            "context_texts": result.context_texts,
            "references": result.references,
            "bounded_history": result.bounded_history,
            "diagnostics": result.diagnostics,
            "events": result.events,
        }

    def prompt(self, payload: PromptPayload) -> dict[str, Any]:
        history = self._history(payload)
        retrieval_result: dict[str, Any] | None = None
        context_texts = payload.context_texts

        if context_texts is None:
            retrieval_result = self.pipeline(StagePayload(**payload.model_dump()))
            context_texts = retrieval_result["context_texts"]
            history = retrieval_result["bounded_history"]

        messages = prompt.build_messages(payload.query, history, context_texts)
        return {
            "retrieval": retrieval_result,
            "history": history,
            "messages": messages,
            "prompt_tokens_estimate": prompt.estimate_prompt_tokens(messages),
        }

    def _prepared(self, payload: StagePayload) -> PreparedQuery:
        return preprocess_query(
            payload.query,
            payload.user_id,
            self._history(payload),
            self.postgres,
        )

    def _embeddings(self, payload: StagePayload) -> QueryEmbeddings:
        prepared = self._prepared(payload)
        hyde_text = payload.hyde_text or generate_hyde(prepared)[0]
        return embed_query(self.vector_store, prepared, hyde_text)

    def _sources(self, payload: StagePayload):
        prepared = self._prepared(payload)
        hyde_text = payload.hyde_text or generate_hyde(prepared)[0]
        embeddings = embed_query(self.vector_store, prepared, hyde_text)
        metadata_filter = None if payload.role == "admin" else {"user_id": payload.user_id}
        sources, diagnostics = multi_collection_search(
            self.vector_store,
            prepared,
            embeddings,
            metadata_filter,
            self.postgres,
        )
        return prepared, sources, diagnostics

    @staticmethod
    def _search_events(sources, diagnostics: dict[str, Any]) -> list[str]:
        candidate_count = sum(len(hits) for hits in sources.values())
        events = [
            f"retrieval search completed: sources={len(sources)} candidates={candidate_count}"
        ]
        if diagnostics["source_errors"]:
            events.append(
                f"retrieval search partial failure: sources={len(diagnostics['source_errors'])}"
            )
        return events

    @staticmethod
    def _history(payload: StagePayload | PromptPayload) -> list[dict[str, str]]:
        return [message.model_dump() for message in payload.history]

    @staticmethod
    def _hit(item) -> dict[str, Any]:
        document, score = item
        return {
            "doc_id": document.metadata.get("doc_id"),
            "chunk_id": document.metadata.get("chunk_id"),
            "score": score,
            "text": document.text,
        }
