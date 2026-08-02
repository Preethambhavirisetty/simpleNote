import json

from app.services.ingestion.processors.chunking.chunk_processor import TextChunk
from app.services.ingestion.processors.keywords.keyword_batcher import (
    KeywordBatchItem,
    KeywordBatchResult,
    build_keyword_batches,
    extract_keywords_batched,
    parse_keyword_batch_response,
)
from app.services.ingestion.processors.keywords.entity_extractor import EntityMention
from app.services.ingestion.processors.keywords.keyword_processor import KeywordProcessor
from app.services.ingestion.processors.text_normalization import normalize_text_for_keyword_extraction


def test_keyword_text_normalizes_markdown_tables():
    normalized = normalize_text_for_keyword_extraction(
        "| Quarter | Revenue |\n|---|---|\n| Q1 | 12M |\n| Q2 | 15M |"
    )

    assert "|" not in normalized
    assert "Quarter Q1 Revenue 12M" in normalized
    assert "Quarter Q2 Revenue 15M" in normalized


def test_keyword_extraction_text_prepends_heading_context_only_when_needed():
    metadata = {
        "heading_context": "Incident Log > Qdrant OOM",
        "has_heading_context": True,
    }

    assert KeywordProcessor._keyword_extraction_text(
        "Consumer lag cleared.", "Consumer lag cleared.", metadata
    ) == "Incident Log > Qdrant OOM\n\nConsumer lag cleared."
    assert KeywordProcessor._keyword_extraction_text(
        "## Qdrant OOM\n\nConsumer lag cleared.",
        "## Qdrant OOM.\n\nConsumer lag cleared.",
        metadata,
    ) == "## Qdrant OOM.\n\nConsumer lag cleared."


def test_keyword_batches_honor_chunk_and_token_limits_and_mark_truncation():
    items = [
        KeywordBatchItem(str(index), "content", "token " * 50)
        for index in range(3)
    ]

    batches = build_keyword_batches(items, max_chunks=2, max_tokens=60)

    assert len(batches) == 3
    assert all(len(batch) == 1 for batch in batches)
    assert not any(item.truncated for batch in batches for item in batch)

    oversized = build_keyword_batches(
        [KeywordBatchItem("large", "content", "token " * 100)],
        max_chunks=10,
        max_tokens=20,
    )
    assert oversized[0][0].truncated is True


def test_keyword_batch_response_recovers_valid_objects_around_malformed_content():
    response = """
    [
      {"chunk_id": "0", "keywords": ["Qdrant", "vector search"]},
      {"chunk_id": "broken", "keywords": [},
      {"chunk_id": "1", "keywords": ["Kafka", 42, "Kafka"]}
    ]
    """

    parsed = parse_keyword_batch_response(
        response,
        allowed_chunk_ids={"0", "1", "2"},
        keywords_per_chunk=10,
    )

    assert parsed == {
        "0": ["Qdrant", "vector search"],
        "1": ["Kafka"],
    }


def test_keyword_batch_retries_once_and_preserves_missing_chunks():
    calls = []

    def fake_llm(messages, **kwargs):
        calls.append((messages, kwargs))
        if len(calls) == 1:
            raise RuntimeError("temporary")
        return json.dumps([{"chunk_id": "0", "keywords": ["Qdrant OOM resolution"]}])

    result = extract_keywords_batched(
        [
            KeywordBatchItem("0", "content", "Qdrant recovered."),
            KeywordBatchItem("1", "content", "Consumer lag cleared."),
        ],
        system_prompt="extract",
        max_chunks=10,
        max_tokens=3000,
        concurrency=1,
        keywords_per_chunk=10,
        llm_call=fake_llm,
    )

    assert result.keywords_by_chunk == {
        "0": ["Qdrant OOM resolution"],
        "1": [],
    }
    assert result.api_calls == 3
    assert result.retries == 2
    assert "keyword extraction missing recovery api call: batch=1 chunks=1 output_tokens=80" in result.events
    assert calls[-1][1]["max_tokens"] == 80
    assert calls[-1][1]["temperature"] == 0
    assert calls[-1][1]["model"] == "summarizer"


def test_keyword_processor_keeps_short_chunk_entities_but_skips_its_keywords(monkeypatch):
    monkeypatch.setattr(
        "app.services.ingestion.processors.keywords.keyword_processor.extract_entity_mentions_batch",
        lambda texts: [[EntityMention("Qdrant", "PRODUCT")] for _text in texts],
    )
    monkeypatch.setattr(
        "app.services.ingestion.processors.keywords.keyword_processor.extract_keywords_batched",
        lambda items, **kwargs: KeywordBatchResult(
            keywords_by_chunk={item.chunk_id: ["collection recovery"] for item in items},
            api_calls=1 if items else 0,
            retries=0,
            events=["keyword extraction batches prepared: 1"] if items else [],
        ),
    )
    chunks = [
        TextChunk(
            content="Qdrant",
            chunk_id="0",
            metadata={"skip_keywords": True, "skip_keywords_reason": "short_chunk"},
        ),
        TextChunk(content="Consumer lag cleared after collection recovery.", chunk_id="1"),
    ]

    processor = KeywordProcessor(use_llm_dedup=False)
    results, top_keywords, top_entities = processor.process(chunks)

    assert results[0].keywords == []
    assert results[0].entities == ["Qdrant"]
    assert results[1].keywords == ["collection recovery"]
    assert top_keywords == ["collection recovery"]
    assert top_entities == ["Qdrant"]
    assert processor.api_call_counts["keyword_extraction"] == 1
    assert "keywords extraction skipped: chunk=0 reason=quality:short_chunk" in processor.events


def test_global_keyword_ranking_prefers_cross_chunk_frequency_then_specificity():
    processor = KeywordProcessor(use_llm_dedup=False)

    candidates = processor._rank_candidates(
        [
            ["rare detailed concept", "common topic"],
            ["common topic", "specific shared concept"],
            ["common topic", "specific shared concept"],
        ],
        kind="kw",
    )

    assert [candidate.term for candidate in candidates[:3]] == [
        "common topic",
        "specific shared concept",
        "rare detailed concept",
    ]


def test_llm_dedup_rejects_candidates_without_refilling(monkeypatch):
    captured = {}

    def fake_llm(messages, **kwargs):
        captured["content"] = messages[-1]["content"]
        return "shared concept"

    monkeypatch.setattr(
        "app.services.ingestion.processors.keywords.keyword_processor.llm_call_general",
        fake_llm,
    )
    processor = KeywordProcessor(use_llm_dedup=True)
    candidates = processor._rank_candidates(
        [["shared concept"], ["shared concept", "specific detail"]],
        kind="kw",
    )

    assert processor._deduplicate_candidates(candidates, kind="kw") == ["shared concept"]
    assert "term: shared concept | section_frequency: 2" in captured["content"]
    assert processor.api_call_counts["keyword_dedup"] == 1
