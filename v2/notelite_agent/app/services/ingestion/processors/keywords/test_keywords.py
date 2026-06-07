from app.services.ingestion.processors.chunking.chunk_processor import TextChunk
from app.services.ingestion.processors.keywords.keyword_processor import KeywordProcessor
from app.services.ingestion.processors.text_normalization import (
    normalize_text_for_keyword_extraction,
)


def test_keyword_text_normalizes_markdown_tables():
    text = """
| Quarter | Revenue |
|---------|---------|
| Q1 | 12M |
| Q2 | 15M |
"""

    normalized = normalize_text_for_keyword_extraction(text)

    assert "|" not in normalized
    assert "Quarter Q1 Revenue 12M" in normalized
    assert "Quarter Q2 Revenue 15M" in normalized


def test_keyword_text_repairs_ocr_hyphenation():
    normalized = normalize_text_for_keyword_extraction("experi-\nence and imple-\nmentation")

    assert "experience" in normalized
    assert "implementation" in normalized
    assert "imple-" not in normalized


def test_keyword_processor_extracts_from_normalized_content(monkeypatch):
    seen = {}

    def fake_extract(text, top_n):
        seen["text"] = text
        return ["Quarter Revenue"], []

    monkeypatch.setattr(
        "app.services.ingestion.processors.keywords.keyword_processor.extract_keywords",
        fake_extract,
    )

    KeywordProcessor(use_llm_dedup=False).process(
        [
            """
## Revenue
| Quarter | Revenue |
|---------|---------|
| Q1 | 12M |
"""
        ]
    )

    assert "|" not in seen["text"]
    assert "Quarter Q1 Revenue 12M" in seen["text"]


def test_keyword_processor_skips_only_non_text_structures(monkeypatch):
    calls = []

    def fake_extract(text, top_n):
        calls.append(text)
        return ["customer retention"], ["Acme Holdings"]

    monkeypatch.setattr(
        "app.services.ingestion.processors.keywords.keyword_processor.extract_keywords",
        fake_extract,
    )

    chunks = [
        TextChunk(content="## Empty", chunk_id="0", chunk_type="heading_only"),
        TextChunk(content="Acme Holdings\n100 Main Street", chunk_id="1", chunk_type="address"),
        TextChunk(content="ARR: Annual Recurring Revenue", chunk_id="2", chunk_type="glossary"),
        TextChunk(content="```python\ndef thing():\n    return 1\n```", chunk_id="3", chunk_type="code"),
    ]

    results, top_keywords, top_entities = KeywordProcessor(use_llm_dedup=False).process(chunks)

    assert calls == ["Acme Holdings.\n100 Main Street.", "ARR: Annual Recurring Revenue."]
    assert results[0].keywords == []
    assert results[1].keywords == ["customer retention"]
    assert results[2].keywords == ["customer retention"]
    assert results[3].keywords == []
    assert top_keywords == ["customer retention"]
    assert top_entities == ["Acme Holdings"]


def test_table_chunks_use_natural_language_augmentation_before_extraction(monkeypatch):
    seen = {}

    def fake_extract(text, top_n):
        seen["text"] = text
        return ["timeout value"], ["Kafka"]

    monkeypatch.setattr(
        "app.services.ingestion.processors.keywords.keyword_processor.extract_keywords",
        fake_extract,
    )
    chunk = TextChunk(
        content="| Setting | Value |\n| --- | --- |\n| timeout | 30 |\n| broker | Kafka |",
        chunk_id="0",
        chunk_type="table",
        metadata={"heading_context": "Platform > Configuration"},
    )

    KeywordProcessor(use_llm_dedup=False).process([chunk])

    assert "Table from section: Platform > Configuration." in seen["text"]
    assert "Columns: Setting, Value." in seen["text"]
    assert "Setting timeout, Value 30." in seen["text"]
    assert "|" not in seen["text"]


def test_global_keyword_ranking_prefers_cross_chunk_frequency_then_specificity(monkeypatch):
    extracted = iter([
        (["rare detailed concept", "common topic", "repeated local"], []),
        (["common topic", "specific shared concept"], []),
        (["common topic", "specific shared concept"], []),
    ])

    monkeypatch.setattr(
        "app.services.ingestion.processors.keywords.keyword_processor.extract_keywords",
        lambda text, top_n: next(extracted),
    )
    chunks = [
        TextChunk(content="Chunk content long enough for extraction one.", chunk_id="0"),
        TextChunk(content="Chunk content long enough for extraction two.", chunk_id="1"),
        TextChunk(content="Chunk content long enough for extraction three.", chunk_id="2"),
    ]

    _, top_keywords, _ = KeywordProcessor(use_llm_dedup=False).process(chunks)

    assert top_keywords[:3] == ["common topic", "specific shared concept", "rare detailed concept"]


def test_llm_dedup_input_includes_cross_chunk_ranking_metadata(monkeypatch):
    captured = {}

    def fake_llm(messages):
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

    result = processor._deduplicate_candidates(candidates, kind="kw")

    assert result[0] == "shared concept"
    assert "term: shared concept | chunk_frequency: 2" in captured["content"]
    assert "specificity:" in captured["content"]


def test_keyword_processor_respects_chunk_quality_skip_flag(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.services.ingestion.processors.keywords.keyword_processor.extract_keywords",
        lambda text, top_n: calls.append(text) or (["ignored"], []),
    )
    chunk = TextChunk(
        content="Broken OCR text",
        chunk_id="0",
        metadata={"skip_keywords": True, "skip_keywords_reason": "ocr_single_character_noise"},
    )

    processor = KeywordProcessor(use_llm_dedup=False)
    results, top_keywords, _ = processor.process([chunk])

    assert calls == []
    assert results[0].keywords == []
    assert top_keywords == []
    assert "keywords skipped: 1 chunks" in processor.events
