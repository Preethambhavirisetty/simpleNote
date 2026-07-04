"""Late staleness re-checks in the ingestion pipeline.

The version guard at task start is not enough: steps 1-3 (chunking/keywords) and
step 5 (summarization) take seconds of LLM work, during which a newer version of
the note may be committed. The orchestrator must re-check right before each
write group and skip instead of overwriting newer content.
"""
from unittest.mock import MagicMock, patch

from app.services.ingestion.orchestrator import IngestionOrchestrator


def make_orchestrator():
    orchestrator = IngestionOrchestrator.__new__(IngestionOrchestrator)

    orchestrator.chunk_processor = MagicMock(events=[])
    orchestrator.chunk_processor.process.return_value = ["chunk"]

    orchestrator.keyword_processor = MagicMock(
        events=[],
        api_calls=0,
        api_call_counts={
            "keyword_extraction": 0,
            "keyword_extraction_retries": 0,
            "keyword_dedup": 0,
            "entity_dedup": 0,
        },
    )
    orchestrator.keyword_processor.process.return_value = (["chunk"], [], [])

    summary = MagicMock(
        events=[], summary="s", questions=[], summary_api_calls=0, question_api_calls=0
    )
    orchestrator.summarization_pipeline = MagicMock(summary_ms=1.0, questions_ms=1.0)
    orchestrator.summarization_pipeline.run.return_value = summary

    orchestrator._vector_store = MagicMock(events=[])
    orchestrator.postgres_store = MagicMock()
    orchestrator.postgres_store.user_timezone.return_value = "UTC"
    return orchestrator


def payload():
    return {"user_id": "u", "folder_id": "f", "note_id": "n", "text": "hello", "version": 1}


def run_with_staleness(orchestrator, stale_sequence):
    orchestrator._is_stale_upsert = MagicMock(side_effect=stale_sequence)
    with patch("app.services.ingestion.orchestrator.ChunkBuilder") as chunk_builder, \
         patch("app.services.ingestion.orchestrator.SummaryBuilder") as summary_builder, \
         patch("app.services.ingestion.orchestrator.DateExtractor") as date_extractor:
        chunk_builder.return_value = MagicMock(events=[])
        chunk_builder.return_value.build.return_value = []
        summary_builder.return_value = MagicMock(events=[])
        date_extractor.return_value = MagicMock(events=[])
        date_extractor.return_value.extract.return_value = []
        return orchestrator.run(payload())


def test_stale_before_chunk_write_skips_all_writes():
    orchestrator = make_orchestrator()

    result = run_with_staleness(orchestrator, [False, True])

    assert result["status"] == "skipped"
    assert result["stage"] == "pre_chunk_write"
    orchestrator._vector_store.replace_index_chunks.assert_not_called()
    orchestrator._vector_store.upsert_summary_artifacts.assert_not_called()
    orchestrator.postgres_store.replace_document.assert_not_called()


def test_stale_before_summary_write_stops_after_chunks():
    """Chunks already written are superseded by the newer task's own replace;
    the stale task must not go on to write summary/postgres artifacts."""
    orchestrator = make_orchestrator()

    result = run_with_staleness(orchestrator, [False, False, True])

    assert result["status"] == "skipped"
    assert result["stage"] == "pre_summary_write"
    orchestrator._vector_store.replace_index_chunks.assert_called_once()
    orchestrator._vector_store.upsert_summary_artifacts.assert_not_called()
    orchestrator.postgres_store.replace_document.assert_not_called()


def test_current_version_writes_normally():
    orchestrator = make_orchestrator()

    result = run_with_staleness(orchestrator, [False, False, False])

    assert result["status"] == "processed"
    orchestrator._vector_store.replace_index_chunks.assert_called_once()
    orchestrator._vector_store.upsert_summary_artifacts.assert_called_once()
    orchestrator.postgres_store.replace_document.assert_called_once()
