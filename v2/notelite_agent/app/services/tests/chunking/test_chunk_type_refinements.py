from app.services.ingestion.processors.chunking.chunk_classifier import classify_chunk


def test_heading_with_metadata_fields_is_not_a_glossary():
    text = "# Team Meeting\n\nDate: Thursday, June 6, 2024\nAttendees: Alex Morgan, Sam Lee"

    assert classify_chunk(text) == "content"


def test_explicit_glossary_heading_allows_definition_pairs():
    text = "## Glossary\n\nAPI: Application Programming Interface\nSDK: Software Development Kit"

    assert classify_chunk(text) == "glossary"
