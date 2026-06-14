from llama_index.core import Document

from app.services.chat.pipeline import retrieval_pipeline
from app.services.chat.pipeline.retrieval_pipeline import (
    PreparedQuery,
    QueryEmbeddings,
    generate_hyde,
    preprocess_query,
    run_retrieval,
    weighted_rrf,
)
from app.services.chat.schema import ChatRequest


class FakePostgres:
    def user_timezone(self, user_id):
        return "UTC"


def hit(doc_id: str, chunk_id: str):
    return (
        Document(
            id_=f"{doc_id}-{chunk_id}",
            text="body",
            metadata={"doc_id": doc_id, "chunk_id": chunk_id},
        ),
        1.0,
    )


def test_chat_request_no_longer_requires_tenant_id():
    assert ChatRequest(query="hello", user_id="u").user_id == "u"


def test_preprocess_normalizes_and_contextualizes_short_followup():
    result = preprocess_query(
        "  when?  ",
        "u",
        [{"role": "assistant", "content": "We discussed Qdrant."}],
        FakePostgres(),
    )

    assert result.original_query == "when?"
    assert "Qdrant" in result.search_query


def test_weighted_rrf_deduplicates_by_document_and_chunk():
    ranked, diagnostics = weighted_rrf({
        "chunk_dense_original": [hit("a", "0"), hit("a", "1")],
        "chunk_sparse_bm25": [hit("a", "0")],
    })

    identities = [
        (document.metadata["doc_id"], document.metadata["chunk_id"])
        for document, _score in ranked
    ]
    assert identities == [("a", "0"), ("a", "1")]
    assert diagnostics["source_counts"]["chunk_sparse_bm25"] == 1


def test_hyde_failure_is_nonfatal(monkeypatch):
    def raise_timeout(*args, **kwargs):
        raise TimeoutError

    monkeypatch.setattr(retrieval_pipeline, "llm_call_general", raise_timeout)

    value, status = generate_hyde(PreparedQuery("q", "q"))

    assert value is None
    assert status.startswith("fallback:")


def test_full_retrieval_returns_concise_stage_events(monkeypatch):
    seed = hit("doc", "0")
    monkeypatch.setattr(
        retrieval_pipeline,
        "preprocess_query",
        lambda *args: PreparedQuery("query", "query"),
    )
    monkeypatch.setattr(
        retrieval_pipeline,
        "generate_hyde",
        lambda prepared: (None, "fallback:TimeoutError"),
    )
    monkeypatch.setattr(
        retrieval_pipeline,
        "embed_query",
        lambda *args: QueryEmbeddings([0.1], {"indices": [], "values": []}),
    )
    monkeypatch.setattr(
        retrieval_pipeline,
        "multi_collection_search",
        lambda *args: (
            {"chunk_dense_original": [seed]},
            {"source_errors": {}, "summary_doc_ids": [], "date_identity_count": 0},
        ),
    )
    monkeypatch.setattr(
        retrieval_pipeline,
        "weighted_rrf",
        lambda sources: ([seed], {"source_counts": {"chunk_dense_original": 1}}),
    )
    monkeypatch.setattr(retrieval_pipeline, "rerank", lambda *args, **kwargs: [seed])
    monkeypatch.setattr(
        retrieval_pipeline,
        "assemble_context",
        lambda *args: (["body"], [], {"expanded_context_count": 1}),
    )

    result = run_retrieval(object(), "query", "user", 5, "user", postgres=FakePostgres())

    assert result.events == [
        "retrieval started",
        "retrieval preprocess completed: temporal=False",
        "retrieval hyde fallback:TimeoutError",
        "retrieval embedding completed: hyde=False",
        "retrieval search completed: sources=1 candidates=1",
        "retrieval rrf completed: candidates=1",
        "retrieval rerank completed: seeds=1",
        "retrieval context completed: chunks=1 sources=0",
        "retrieval completed",
    ]
