from llama_index.core import Document

from app.services.chat.pipeline import retrieval_pipeline
from app.services.chat.pipeline.retrieval_pipeline import (
    PreparedQuery,
    assemble_context,
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

def test_hyde_rejects_unsupported_numbers(monkeypatch):
    monkeypatch.setattr(
        retrieval_pipeline,
        "llm_call_general",
        lambda *args, **kwargs: "The note records a 20% ownership offer.",
    )

    value, status = generate_hyde(PreparedQuery("What ownership was offered?", "q"))

    assert value is None
    assert status == "rejected:unsupported_numbers"

def test_hyde_allows_numbers_present_in_query(monkeypatch):
    monkeypatch.setattr(
        retrieval_pipeline,
        "llm_call_general",
        lambda *args, **kwargs: "The note discusses release v2.1.0.",
    )

    value, status = generate_hyde(PreparedQuery("What happened to v2.1.0?", "q"))

    assert value == "The note discusses release v2.1.0."
    assert status == "completed"

def test_context_limits_seeds_and_expands_only_top_small_fragment(monkeypatch):
    monkeypatch.setattr(retrieval_pipeline, "RETRIEVAL_CONTEXT_SEED_LIMIT", 2)
    monkeypatch.setattr(retrieval_pipeline, "RETRIEVAL_NEIGHBOR_SEED_LIMIT", 1)

    def document(chunk_id, text, index, previous=None, next_id=None):
        return Document(
            text=text,
            metadata={
                "doc_id": "doc",
                "chunk_id": chunk_id,
                "chunk_index": index,
                "note_id": "note",
                "prev_chunk_id": previous,
                "next_chunk_id": next_id,
            },
        )

    neighbor = document("0", "previous", 0)
    first = document("1", "small fragment", 1, previous="0", next_id="2")
    second = document("2", "second seed", 2, previous="1", next_id="3")
    third = document("3", "third seed", 3)

    class Store:
        def fetch_neighbor(self, doc_id, chunk_id):
            return {"0": neighbor, "2": second}.get(str(chunk_id))

    class Postgres:
        def skipped_chunk(self, doc_id, chunk_id):
            return None

        def summaries(self, doc_ids, limit):
            return []

    contexts, references, diagnostics = assemble_context(
        Store(),
        Postgres(),
        [(first, 1.0), (second, 0.9), (third, 0.8)],
    )

    assert contexts == ["previous", "small fragment", "second seed"]
    assert references[0]["chunk_ids"] == ["0", "1", "2"]
    assert [chunk["text"] for chunk in references[0]["chunks"]] == contexts
    assert [chunk["is_seed"] for chunk in references[0]["chunks"]] == [False, True, True]
    assert [chunk["score"] for chunk in references[0]["chunks"]] == [None, 1.0, 0.9]
    assert diagnostics["context_seed_count"] == 2
    assert diagnostics["neighbor_count"] == 2
