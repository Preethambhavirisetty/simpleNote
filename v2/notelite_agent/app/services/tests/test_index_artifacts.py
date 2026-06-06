from types import SimpleNamespace

from app.core.embeddings import EmbeddingBatch
from app.services.ingestion.actions.services import IngestionActionServices
from app.services.ingestion.processors.ingest.document_builder import DocumentBuilder
from app.services.ingestion.processors.keywords.keyword_processor import ChunkKeywordResult
from app.services.ingestion.storage.vector_store import QdrantVectorStore


def _chunk(chunk_id: str, content: str, chunk_type: str, index: int, total: int, **metadata):
    return ChunkKeywordResult(
        chunk_id=chunk_id,
        content=content,
        chunk_type=chunk_type,
        keywords=[f"keyword-{chunk_id}"],
        entities=[f"entity-{chunk_id}"],
        metadata=metadata,
        chunk_index=index,
        total_chunks=total,
    )


def test_document_builder_creates_index_ready_artifacts_and_indexable_adjacency():
    chunks = [
        _chunk(
            "0",
            "# Root\n\n## Section\n\nBody text.",
            "content",
            0,
            3,
            h1="Root",
            h2="Section",
            heading_context="Root > Section",
        ),
        _chunk("1", "Page 1 of 1", "content", 1, 3),
        _chunk(
            "2",
            "| Name | Value |\n| --- | --- |\n| timeout | 30 |",
            "table",
            2,
            3,
            heading_context="Root > Settings",
        ),
    ]

    _, documents = DocumentBuilder().build(
        data={"user_id": "u", "folder_id": "f", "note_id": "n"},
        doc_id="u-f-n",
        chunk_objects=chunks,
        top_kw=[],
        top_ent=[],
        questions=[],
        note_summary="",
    )

    assert len(documents) == 3
    assert documents[0].text == "Root > Section\n\nBody text."
    assert documents[0].metadata["content"] == chunks[0].content
    assert documents[0].metadata["next_chunk_id"] == "1"
    assert "prev_chunk_id" not in documents[0].metadata
    assert documents[1].metadata["skip_indexing"] is False
    assert documents[1].metadata["skip_reason"] == ""
    assert documents[1].metadata["prev_chunk_id"] == "0"
    assert documents[1].metadata["next_chunk_id"] == "2"
    assert documents[2].metadata["prev_chunk_id"] == "1"
    assert documents[2].text.startswith("Table from section: Root > Settings.")

    artifact = IngestionActionServices._document_payload(documents[0])
    assert artifact["content"] == chunks[0].content
    assert artifact["embed_text"] == "Root > Section\n\nBody text."
    assert artifact["skip_indexing"] is False
    assert artifact["metadata"]["next_chunk_id"] == "1"


class _FakeClient:
    def __init__(self):
        self.points = []

    def upsert(self, *, collection_name, points):
        self.points = points


class _FakeEmbeddingClient:
    def __init__(self):
        self.remote_service = SimpleNamespace(model="test-embedding-model")
        self.events = []
        self.texts = []

    def embed_documents(self, texts):
        self.texts = list(texts)
        return EmbeddingBatch(
            dense=[[0.1, 0.2] for _ in texts],
            sparse=[{"indices": [], "values": []} for _ in texts],
        )


def test_vector_store_embeds_embed_text_and_stores_original_content():
    chunks = [
        _chunk("0", "# Root\n\nBody text.", "content", 0, 2, heading_context="Root"),
        _chunk("1", "Page 1 of 1", "content", 1, 2),
    ]
    _, documents = DocumentBuilder().build(
        data={"user_id": "u", "folder_id": "f", "note_id": "n"},
        doc_id="u-f-n",
        chunk_objects=chunks,
        top_kw=[],
        top_ent=[],
        questions=[],
        note_summary="",
    )

    store = QdrantVectorStore.__new__(QdrantVectorStore)
    store.client = _FakeClient()
    store.embedding_client = _FakeEmbeddingClient()
    store.events = []
    store.upsert_chunks(documents)

    assert store.embedding_client.texts == ["Root\n\nBody text.", "Page 1 of 1"]
    assert len(store.client.points) == 2
    payload = store.client.points[0].payload
    assert payload["content"] == "# Root\n\nBody text."
    assert payload["embed_text"] == "Root\n\nBody text."
    assert payload["chunk_index"] == 0
    assert payload["total_chunks"] == 2
    assert payload["metadata"]["embedding_model"] == "test-embedding-model"
    assert payload["metadata"]["embedding_dim"] == 2
    assert payload["metadata"]["indexed_at"]
    assert not any(event.startswith("chunk vectors skipped:") for event in store.events)
