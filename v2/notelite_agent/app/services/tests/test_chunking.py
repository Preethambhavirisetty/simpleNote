import pytest

from app.services.ingestion.actions.schema import ChunkPayload
from app.services.ingestion.actions.services import IngestionActionServices
from app.services.ingestion.processors.chunking.chunk_processor import ChunkProcessor
from app.services.tests.chunk_test_data_stress import TEST_CASES


def _case_id(case: dict) -> str:
    return case["name"]


def _chunk_text(chunks) -> str:
    return "\n\n".join(chunk.content for chunk in chunks)


@pytest.mark.parametrize("case", TEST_CASES, ids=_case_id)
def test_chunk_test_data_expectations(case):
    chunks = ChunkProcessor().process(case["text"])
    expected = case["expected"]

    if "chunk_count" in expected:
        assert len(chunks) == expected["chunk_count"]
    if "chunk_count_min" in expected:
        assert len(chunks) >= expected["chunk_count_min"]

    chunk_types = [chunk.chunk_type for chunk in chunks]
    for chunk_type in expected.get("chunk_types", []):
        assert chunk_type in chunk_types

    text = _chunk_text(chunks)
    for fragment in expected.get("must_contain", []):
        assert fragment in text

    for fragment in expected.get("must_not_split", []):
        containing_chunks = [chunk for chunk in chunks if fragment in chunk.content]
        assert len(containing_chunks) == 1


@pytest.mark.parametrize(
    "case",
    [
        case
        for case in TEST_CASES
        if case["expected"].get("chunk_count") == 1
        and case["expected"].get("must_not_split")
    ],
    ids=_case_id,
)
def test_declared_atomic_chunks_keep_fragments_together(case):
    chunks = ChunkProcessor().process(case["text"])
    expected_fragments = case["expected"]["must_not_split"]

    assert len(chunks) == 1
    for fragment in expected_fragments:
        assert fragment in chunks[0].content


def test_chunk_processor_records_and_resets_events_per_call():
    processor = ChunkProcessor()

    processor.process("First paragraph.")
    first_events = list(processor.events)
    processor.process("Second paragraph.\n\n---\n\nThird paragraph.")

    assert first_events[0].startswith("chunking started:")
    assert first_events[-1] == "chunking completed: 1 chunks"
    assert processor.events[0].startswith("chunking started:")
    assert processor.events[-1] == "chunking completed: 2 chunks"
    assert sum(event.startswith("chunking started:") for event in processor.events) == 1


def test_chunk_action_returns_chunking_events():
    result = IngestionActionServices().chunk(ChunkPayload(text="Before.\n\n---\n\nAfter."))

    assert result["chunk_count"] == 2
    assert result["events"][0].startswith("chunking started:")
    assert result["events"][-1] == "chunking completed: 2 chunks"


def test_final_chunks_include_ordering_and_size_metadata():
    chunks = ChunkProcessor().process("# Root\n\n## First\n\nFirst body.\n\n## Second\n\nSecond body.")

    assert [chunk.chunk_index for chunk in chunks] == [0, 1]
    assert [chunk.total_chunks for chunk in chunks] == [2, 2]
    for chunk in chunks:
        assert chunk.metadata["has_heading_context"] is True
        assert chunk.metadata["token_count"] > 0
        assert chunk.metadata["char_count"] == len(chunk.content)


def test_divider_lines_force_boundaries_without_becoming_chunks():
    text = "Before the divider.\n\n------------------------\n\nAfter the divider."

    chunks = ChunkProcessor().process(text)

    assert [chunk.content for chunk in chunks] == ["Before the divider.", "After the divider."]
    assert all("---" not in chunk.content for chunk in chunks)


def test_divider_only_document_produces_no_chunks():
    chunks = ChunkProcessor().process("---\n________\n********")

    assert chunks == []


def test_divider_after_heading_preserves_heading_for_following_prose():
    text = "# Root\n\n## Section\n\n---\n\nFirst prose line.\n\n## Next\n\nNext body."

    chunks = ChunkProcessor().process(text)

    assert chunks[0].content == "# Root\n\n## Section\n\nFirst prose line."
    assert chunks[0].metadata["heading_context"] == "Root > Section"
    assert not any(chunk.chunk_type == "heading_only" and "## Section" in chunk.content for chunk in chunks)


def test_semantic_splitter_receives_prose_without_heading_lines():
    processor = ChunkProcessor()
    received: list[str] = []

    def split_prose(text: str) -> list[str]:
        received.append(text)
        return ["First prose sentence.", "Second prose sentence."]

    processor.semantic_chunker.split_prose = split_prose
    chunks = processor.process("# Root\n\n## Section\n\n---\n\nFirst prose sentence. Second prose sentence.")

    assert received == ["First prose sentence. Second prose sentence."]
    assert chunks[0].content == "# Root\n\n## Section\n\nFirst prose sentence."
    assert chunks[0].metadata["h2"] == "Section"
    assert chunks[1].metadata["h2"] == "Section"


def test_heading_only_run_does_not_duplicate_shared_ancestor_headings():
    text = "# Root\n\n## Empty A\n\n## Empty B\n\n## Empty C"

    chunks = ChunkProcessor().process(text)

    assert len(chunks) == 1
    assert chunks[0].chunk_type == "heading_only"
    assert chunks[0].content.splitlines() == ["# Root", "", "## Empty A", "", "## Empty B", "", "## Empty C"]


def test_headed_document_is_not_short_circuited_by_contact_signal():
    text = "# Review\n\n## Summary\n\nWork completed.\n\n## Contact\n\nEmail: team@example.com\n\n## Final\n\nDone."

    chunks = ChunkProcessor().process(text)

    assert len(chunks) == 3
    assert [chunk.metadata.get("h2") for chunk in chunks] == ["Summary", "Contact", "Final"]
    assert [chunk.chunk_type for chunk in chunks] == ["content", "contact", "content"]


def test_headed_document_keeps_footer_like_text_as_content_within_sections():
    text = "Cover Page\nPage 1 of 2\n\n# Report\n\n## First\n\nFirst body.\n\nCONFIDENTIAL - INTERNAL USE ONLY\nPage 2 of 2\n\n## Second\n\nSecond body."

    chunks = ChunkProcessor().process(text)

    assert chunks[0].content == "Cover Page\nPage 1 of 2"
    assert all(chunk.chunk_type == "content" for chunk in chunks)
    assert any(chunk.metadata.get("h2") == "First" and "CONFIDENTIAL" in chunk.content for chunk in chunks)
    assert any(chunk.metadata.get("h2") == "Second" and "Second body" in chunk.content for chunk in chunks)
    assert not any("First body" in chunk.content and "Second body" in chunk.content for chunk in chunks)
