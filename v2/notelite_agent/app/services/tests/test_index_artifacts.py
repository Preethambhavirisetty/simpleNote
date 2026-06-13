from types import SimpleNamespace

from app.core.embeddings import EmbeddingBatch
from app.services.ingestion.processors.ingest import (
    ChunkBuilder, DocumentSummary, IndexChunk, SummaryBuilder,
)
from app.services.ingestion.processors.keywords.keyword_processor import ChunkKeywordResult
from app.services.ingestion.processors.summary.summarization_pipeline import SummarizationPipeline
from app.services.ingestion.processors.summary.summary_processor import SummaryResult
from app.services.ingestion.storage.vector_store import (
    CHUNK_COLLECTION, QUESTIONS_COLLECTION, SUMMARY_COLLECTION, QdrantVectorStore,
)


def _chunk(chunk_id: str, content: str, chunk_type: str, index: int, total: int, **metadata):
    return ChunkKeywordResult(
        chunk_id=chunk_id, content=content, chunk_type=chunk_type,
        keywords=[f"keyword-{chunk_id}"], entities=[f"entity-{chunk_id}"],
        metadata=metadata, chunk_index=index, total_chunks=total,
    )


def test_chunk_builder_creates_enriched_artifacts_and_complete_adjacency():
    chunks = [
        _chunk("0", "# Root\n\nBody text with enough meaningful words for indexing.", "content", 0, 3,
               h1="Root", heading_context="Root", has_heading_context=True),
        _chunk("1", "```python\nprint('hello')\n```", "code", 1, 3),
        _chunk("2", "| Name | Value |\n| --- | --- |\n| timeout | 30 |", "table", 2, 3,
               heading_context="Root > Settings", has_heading_context=True),
    ]

    builder = ChunkBuilder({"user_id": "u", "folder_id": "f", "note_id": "n"}, "u-f-n")
    artifacts = builder.build(chunks)

    assert artifacts[0].embed_text == chunks[0].content
    assert artifacts[0].next_chunk_id == "1"
    assert artifacts[1].prev_chunk_id == "0"
    assert artifacts[1].next_chunk_id == "2"
    assert artifacts[1].skip_indexing is True
    assert artifacts[1].skip_reason == "structural:code"
    assert artifacts[2].prev_chunk_id == "1"
    assert artifacts[2].embed_text.startswith("Table from section: Root > Settings.")
    assert "|" not in artifacts[2].embed_text
    assert artifacts[2].metadata["embed_text_token_count"] > 0


def test_chunk_builder_uses_normalized_table_fallback(monkeypatch):
    monkeypatch.setattr(
        "app.services.ingestion.processors.ingest.chunk_builder.augment_markdown_table",
        lambda content, heading: "",
    )
    builder = ChunkBuilder({}, "doc")
    artifact = builder.build([_chunk(
        "0", "| Name | Value |\n| --- | --- |\n| timeout | 30 |", "table", 0, 1
    )])[0]

    assert "Name timeout Value 30" in artifact.embed_text
    assert "|" not in artifact.embed_text
    assert "table augmentation fallback: chunk=0" in builder.events


def test_summarization_pipeline_uses_eligible_embed_text(monkeypatch):
    captured = {}
    pipeline = SummarizationPipeline()

    def fake_summary(texts):
        captured["texts"] = texts
        return SummaryResult(summary="Document summary.", api_calls=1, events=["summary done"] )

    monkeypatch.setattr(pipeline.summary_processor, "process", fake_summary)
    monkeypatch.setattr(pipeline.questions_generator, "process", lambda summary: ["What happened?"])
    pipeline.questions_generator.api_calls = 1
    chunks = [
        IndexChunk("0", "doc", 0, 3, "content", "raw", "enriched content", metadata={"token_count": 20}),
        IndexChunk("1", "doc", 1, 3, "code", "raw code", "raw code", skip_indexing=True, metadata={"token_count": 20}),
        IndexChunk("2", "doc", 2, 3, "contact", "raw contact", "enriched contact", skip_indexing=True, metadata={"token_count": 20}),
    ]

    result = pipeline.run(chunks)

    assert captured["texts"] == ["enriched content", "enriched contact"]
    assert result.summary == "Document summary."
    assert result.questions == ["What happened?"]


def test_summary_builder_creates_independent_summary_and_question_artifacts():
    builder = SummaryBuilder({"user_id": "u", "folder_id": "f", "note_id": "n"}, "u-f-n", ["kw"], ["ent"] )
    artifacts = builder.build(DocumentSummary(summary="Summary text.", questions=["Question one?", "Question two?"]))

    assert artifacts.summary is not None
    assert artifacts.summary.embed_text == "Summary text."
    assert artifacts.summary.keywords == ["kw"]
    assert [question.embed_text for question in artifacts.questions] == ["Question one?", "Question two?"]


class _FakeClient:
    def __init__(self):
        self.upserts = {}

    def upsert(self, *, collection_name, points):
        self.upserts[collection_name] = points


class _FakeEmbeddingClient:
    def __init__(self):
        self.remote_service = SimpleNamespace(model="test-embedding-model")
        self.events = []
        self.texts = []

    def embed_documents(self, texts):
        self.texts.extend(texts)
        return EmbeddingBatch(
            dense=[[0.1, 0.2] for _ in texts],
            sparse=[{"indices": [], "values": []} for _ in texts],
        )


def _store():
    store = QdrantVectorStore.__new__(QdrantVectorStore)
    store.client = _FakeClient()
    store.embedding_client = _FakeEmbeddingClient()
    store.events = []
    return store


def test_vector_store_converts_internal_artifacts_at_boundary():
    store = _store()
    chunk = IndexChunk(
        "0", "doc", 0, 1, "content", "Original content", "Enriched content",
        keywords=["kw"], entities=["ent"], metadata={"note_id": "n", "folder_id": "f"},
    )
    store.upsert_index_chunks([chunk])

    point = store.client.upserts[CHUNK_COLLECTION][0]
    assert store.embedding_client.texts == ["Enriched content"]
    assert point.payload["content"] == "Original content"
    assert point.payload["embed_text"] == "Enriched content"

    artifacts = SummaryBuilder({}, "doc").build(DocumentSummary(
        summary="Summary text.", questions=["What happened?"]
    ))
    store.upsert_summary_artifacts(artifacts)

    assert SUMMARY_COLLECTION in store.client.upserts
    assert QUESTIONS_COLLECTION in store.client.upserts


def test_ingestion_actions_replay_stage_three_contracts(monkeypatch):
    from app.services.ingestion.actions.schema import (
        ActionIndexChunk, ChunkBuildPayload, IndexChunksPayload, IndexSummaryPayload,
        SummaryBuildPayload, SummaryPayload,
    )
    from app.services.ingestion.actions.services import IngestionActionServices

    chunk_build = IngestionActionServices().chunk_build(ChunkBuildPayload(
        user_id="u", folder_id="f", note_id="n",
        chunks=[{
            "chunk_id": "0", "content": "Body text with enough words for indexing.",
            "chunk_type": "content", "keywords": ["Body"], "entities": [],
            "metadata": {"heading_context": "Root", "has_heading_context": True, "token_count": 20},
        }],
    ))
    index_chunk = chunk_build["chunks"][0]
    assert index_chunk["embed_text"] == "Root\n\nBody text with enough words for indexing."

    captured = {}
    def fake_process(texts):
        captured["texts"] = texts
        return SummaryResult(summary="A useful summary.", api_calls=1, events=["summary done"])

    monkeypatch.setattr(
        "app.services.ingestion.processors.summary.summary_processor.SummaryProcessor.process",
        lambda self, texts: fake_process(texts),
    )
    monkeypatch.setattr(
        "app.services.ingestion.processors.summary.questions_generator.QuestionsGenerator.process",
        lambda self, summary: ["What is summarized?"],
    )

    summary = IngestionActionServices().summary(SummaryPayload(
        chunks=[ActionIndexChunk(**index_chunk)]
    ))
    assert captured["texts"] == [index_chunk["embed_text"]]
    assert summary["summary"] == "A useful summary."
    assert summary["questions"] == ["What is summarized?"]

    artifacts = IngestionActionServices().summary_build(SummaryBuildPayload(
        user_id="u", folder_id="f", note_id="n",
        summary=summary["summary"], questions=summary["questions"],
        top_keywords=["Body"], entities=[],
    ))
    assert artifacts["summary"]["embed_text"] == "A useful summary."
    assert artifacts["questions"][0]["embed_text"] == "What is summarized?"

    class FakeStore:
        def __init__(self):
            self.events = []
            self.indexed_chunks = None
            self.indexed_summary = None
        def replace_index_chunks(self, doc_id, chunks):
            self.indexed_chunks = (doc_id, chunks)
            self.events = ["chunk vector ingestion completed"]
        def ensure_collections(self):
            self.events.append("collections ensured")
        def upsert_summary_artifacts(self, artifacts):
            self.indexed_summary = artifacts
            self.events.extend(["summary vector upserted", "question vectors upserted: 1"])

    store = FakeStore()
    services = IngestionActionServices(store)
    assert services.index_chunks(IndexChunksPayload(document_id="u-f-n", chunks=[ActionIndexChunk(**index_chunk)]))["events"] == [
        "chunk vector ingestion completed"
    ]
    assert store.indexed_chunks[0] == "u-f-n"

    index_summary = services.index_summary(IndexSummaryPayload(
        summary=artifacts["summary"], questions=artifacts["questions"]
    ))
    assert index_summary["events"] == [
        "summary vector ingestion started", "collections ensured",
        "summary vector upserted", "question vectors upserted: 1",
        "summary vector ingestion completed",
    ]
    assert store.indexed_summary.summary.content == "A useful summary."
