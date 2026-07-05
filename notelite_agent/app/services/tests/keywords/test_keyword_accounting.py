from app.services.ingestion.processors.chunking import TextChunk
from app.services.ingestion.processors.keywords.keyword_batcher import KeywordBatchResult
from app.services.ingestion.processors.keywords.entity_extractor import EntityMention
from app.services.ingestion.processors.keywords.keyword_processor import KeywordProcessor


def test_keyword_processor_accounts_for_extraction_retries_and_two_final_dedup_calls(monkeypatch):
    monkeypatch.setattr(
        "app.services.ingestion.processors.keywords.keyword_processor.extract_keywords_batched",
        lambda items, **kwargs: KeywordBatchResult(
            keywords_by_chunk={item.chunk_id: ["collection recovery"] for item in items},
            api_calls=2,
            retries=1,
            events=[],
        ),
    )
    monkeypatch.setattr(
        "app.services.ingestion.processors.keywords.keyword_processor.extract_entity_mentions_batch",
        lambda texts: [[EntityMention("Qdrant", "PRODUCT")] for _text in texts],
    )

    def fake_dedup(messages, **kwargs):
        return "Qdrant" if "named entity" in messages[0]["content"] else "collection recovery"

    monkeypatch.setattr(
        "app.services.ingestion.processors.keywords.keyword_processor.llm_call_general",
        fake_dedup,
    )

    processor = KeywordProcessor()
    processor.process([
        TextChunk(content="Qdrant collection recovery completed.", chunk_id="0")
    ])

    assert processor.api_call_counts == {
        "keyword_extraction": 2,
        "keyword_extraction_retries": 1,
        "keyword_dedup": 1,
        "entity_dedup": 1,
    }
    assert processor.api_calls == 4
