from app.services.ingestion.processors.chunking import TextChunk
from app.services.ingestion.processors.keywords.entity_extractor import EntityMention
from app.services.ingestion.processors.keywords.keyword_processor import KeywordProcessor


def test_keyword_batch_failure_does_not_discard_spacy_entities(monkeypatch):
    monkeypatch.setattr(
        "app.services.ingestion.processors.keywords.keyword_processor.extract_entity_mentions_batch",
        lambda texts: [[EntityMention("Qdrant", "PRODUCT")] for _text in texts],
    )
    monkeypatch.setattr(
        "app.services.ingestion.processors.keywords.keyword_processor.extract_keywords_batched",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("batch setup failed")),
    )

    processor = KeywordProcessor(use_llm_dedup=False)
    results, top_keywords, top_entities = processor.process([
        TextChunk(content="Qdrant recovered after the incident.", chunk_id="0")
    ])

    assert results[0].keywords == []
    assert results[0].entities == ["Qdrant"]
    assert top_keywords == []
    assert top_entities == ["Qdrant"]
    assert "keyword extraction failed: RuntimeError" in processor.events
