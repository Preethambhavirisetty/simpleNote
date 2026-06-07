from app.services.ingestion.processors.chunking import TextChunk
from app.services.ingestion.processors.keywords.keyword_batcher import KeywordBatchResult
from app.services.ingestion.processors.keywords.keyword_processor import KeywordProcessor


def test_keyword_ranking_counts_repeated_semantic_children_as_one_section():
    processor = KeywordProcessor(use_llm_dedup=False)
    candidates = processor._rank_candidates(
        [
            ["incident heading", "collection recovery"],
            ["incident heading", "consumer lag cleared"],
            ["incident heading", "memory enforcement"],
            ["hybrid search"],
            ["hybrid search"],
        ],
        kind="kw",
        group_keys=["Incident", "Incident", "Incident", "Search A", "Search B"],
    )

    by_term = {candidate.term: candidate for candidate in candidates}
    assert by_term["incident heading"].chunk_frequency == 1
    assert by_term["incident heading"].occurrences == 3
    assert by_term["hybrid search"].chunk_frequency == 2


def test_llm_keyword_phrases_are_preserved_without_conjunction_splitting(monkeypatch):
    monkeypatch.setattr(
        "app.services.ingestion.processors.keywords.keyword_processor.extract_entity_mentions_batch",
        lambda texts: [[] for _text in texts],
    )
    monkeypatch.setattr(
        "app.services.ingestion.processors.keywords.keyword_processor.extract_keywords_batched",
        lambda items, **kwargs: KeywordBatchResult(
            keywords_by_chunk={
                item.chunk_id: ["keyword and entity extraction"]
                for item in items
            },
            api_calls=1,
            retries=0,
            events=[],
        ),
    )

    results, top_keywords, _ = KeywordProcessor(use_llm_dedup=False).process([
        TextChunk(content="Keyword and entity extraction improves retrieval.", chunk_id="0")
    ])

    assert results[0].keywords == ["keyword and entity extraction"]
    assert top_keywords == ["keyword and entity extraction"]


def test_entity_dedup_input_includes_spacy_label_and_context(monkeypatch):
    captured = {}

    def fake_llm(messages, **kwargs):
        captured["content"] = messages[-1]["content"]
        return "Qdrant"

    monkeypatch.setattr(
        "app.services.ingestion.processors.keywords.keyword_processor.llm_call_general",
        fake_llm,
    )
    processor = KeywordProcessor()
    candidates = processor._rank_candidates(
        [["Qdrant"]],
        kind="ent",
        evidence={
            "qdrant": {
                "labels": {"PRODUCT"},
                "contexts": ["Qdrant stores vectors for hybrid retrieval."],
            }
        },
    )

    assert processor._deduplicate_candidates(candidates, kind="ent") == ["Qdrant"]
    assert "spacy_labels: PRODUCT" in captured["content"]
    assert "example_context: Qdrant stores vectors" in captured["content"]


def test_entity_postprocessing_prefers_unique_full_person_name():
    processor = KeywordProcessor(use_llm_dedup=False)
    candidates = processor._rank_candidates(
        [["Morgan"], ["Alice Morgan"]],
        kind="ent",
        evidence={
            "morgan": {"labels": {"PERSON"}, "contexts": []},
            "alice morgan": {"labels": {"PERSON"}, "contexts": []},
        },
    )

    assert processor._postprocess_entity_selection(
        ["Morgan", "Alice Morgan"], candidates
    ) == ["Alice Morgan"]


def test_entity_postprocessing_keeps_ambiguous_partial_person_name():
    processor = KeywordProcessor(use_llm_dedup=False)
    candidates = processor._rank_candidates(
        [["Morgan"], ["Alice Morgan"], ["Sam Morgan"]],
        kind="ent",
        evidence={
            "morgan": {"labels": {"PERSON"}, "contexts": []},
            "alice morgan": {"labels": {"PERSON"}, "contexts": []},
            "sam morgan": {"labels": {"PERSON"}, "contexts": []},
        },
    )

    assert processor._postprocess_entity_selection(["Morgan"], candidates) == ["Morgan"]
