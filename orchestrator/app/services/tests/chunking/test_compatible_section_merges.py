from app.services.ingestion.processors.chunking.chunk_processor import ChunkProcessor, TextChunk
from app.services.ingestion.processors.chunking.chunk_types import ChunkType


def chunk(content: str, chunk_type: ChunkType) -> TextChunk:
    return TextChunk(
        content=content,
        chunk_id="0",
        chunk_type=chunk_type.value,
        metadata={"heading_context": "Reference"},
    )


def test_faq_continuation_stays_with_question_in_same_section():
    chunks = ChunkProcessor._merge_compatible_section_chunks([
        chunk("Q: How does it work?", ChunkType.FAQ),
        chunk("The answer continues in explanatory prose.", ChunkType.CONTENT),
    ])

    assert len(chunks) == 1
    assert "Q: How does it work?" in chunks[0].content
    assert "answer continues" in chunks[0].content


def test_glossary_continuation_stays_with_definition_in_same_section():
    chunks = ChunkProcessor._merge_compatible_section_chunks([
        chunk("Term: A concise definition.", ChunkType.GLOSSARY),
        chunk("Additional detail clarifies the same definition.", ChunkType.CONTENT),
    ])

    assert len(chunks) == 1
    assert "concise definition" in chunks[0].content
    assert "Additional detail" in chunks[0].content
