import pytest

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


def test_divider_lines_force_boundaries_without_becoming_chunks():
    text = "Before the divider.\n\n------------------------\n\nAfter the divider."

    chunks = ChunkProcessor().process(text)

    assert [chunk.content for chunk in chunks] == ["Before the divider.", "After the divider."]
    assert all("---" not in chunk.content for chunk in chunks)


def test_divider_only_document_produces_no_chunks():
    chunks = ChunkProcessor().process("---\n________\n********")

    assert chunks == []


def test_headed_document_is_not_short_circuited_by_contact_signal():
    text = "# Review\n\n## Summary\n\nWork completed.\n\n## Contact\n\nEmail: team@example.com\n\n## Final\n\nDone."

    chunks = ChunkProcessor().process(text)

    assert len(chunks) == 3
    assert [chunk.metadata.get("h2") for chunk in chunks] == ["Summary", "Contact", "Final"]
    assert [chunk.chunk_type for chunk in chunks] == ["content", "contact", "content"]


def test_headed_document_splits_inline_footer_bands_and_preamble():
    text = "Cover Page\nPage 1 of 2\n\n# Report\n\n## First\n\nFirst body.\n\nCONFIDENTIAL - INTERNAL USE ONLY\nPage 2 of 2\n\n## Second\n\nSecond body."

    chunks = ChunkProcessor().process(text)

    assert chunks[0].content == "Cover Page"
    assert any(chunk.chunk_type == "footer" for chunk in chunks)
    assert any(chunk.metadata.get("h2") == "First" and "First body" in chunk.content for chunk in chunks)
    assert any(chunk.metadata.get("h2") == "Second" and "Second body" in chunk.content for chunk in chunks)
    assert not any("First body" in chunk.content and "Second body" in chunk.content for chunk in chunks)
