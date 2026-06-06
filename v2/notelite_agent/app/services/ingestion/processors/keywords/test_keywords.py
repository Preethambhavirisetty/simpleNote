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
