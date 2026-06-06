from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from app.services.ingestion.processors.chunking.chunk_type_rules import (
    is_address_type,
    is_appendix_type,
    is_contact_type,
    is_faq_type,
    is_fenced_code_type,
    is_fenced_json_type,
    is_glossary_type,
    is_heading_only_type,
    is_footer_type,
    is_json_type,
    is_list_type,
    is_quote_type,
    is_raw_code_type,
    is_structured_list_type,
    is_table_type,
    is_transcript_type,
    without_leading_heading,
)


class ChunkType(StrEnum):
    CONTENT = "content"
    HEADING_ONLY = "heading_only"
    TABLE = "table"
    CODE = "code"
    JSON = "json"
    FAQ = "faq"
    TRANSCRIPT = "transcript"
    ADDRESS = "address"
    CONTACT = "contact"
    GLOSSARY = "glossary"
    APPENDIX = "appendix"
    QUOTE = "quote"
    LIST = "list"
    STRUCTURED_LIST = "structured_list"
    FOOTER = "footer"


RulePredicate = Callable[[str, str], bool]


@dataclass(frozen=True)
class ChunkTypeRule:
    chunk_type: ChunkType
    matches: RulePredicate


CHUNK_TYPE_RULES: tuple[ChunkTypeRule, ...] = (
    # Footer first — boilerplate should never be misclassified as content
    ChunkTypeRule(ChunkType.FOOTER, is_footer_type),
    ChunkTypeRule(ChunkType.HEADING_ONLY, is_heading_only_type),
    ChunkTypeRule(ChunkType.JSON, is_fenced_json_type),
    ChunkTypeRule(ChunkType.CODE, is_fenced_code_type),
    ChunkTypeRule(ChunkType.JSON, is_json_type),
    ChunkTypeRule(ChunkType.CODE, is_raw_code_type),
    ChunkTypeRule(ChunkType.TABLE, is_table_type),
    ChunkTypeRule(ChunkType.FAQ, is_faq_type),
    ChunkTypeRule(ChunkType.TRANSCRIPT, is_transcript_type),
    # Quote before glossary — em-dash attribution lines overlap
    ChunkTypeRule(ChunkType.QUOTE, is_quote_type),
    # Contact before address — address handler excludes contact internally
    ChunkTypeRule(ChunkType.CONTACT, is_contact_type),
    ChunkTypeRule(ChunkType.ADDRESS, is_address_type),
    ChunkTypeRule(ChunkType.APPENDIX, is_appendix_type),
    ChunkTypeRule(ChunkType.GLOSSARY, is_glossary_type),
    ChunkTypeRule(ChunkType.STRUCTURED_LIST, is_structured_list_type),
    ChunkTypeRule(ChunkType.LIST, is_list_type),
)


def classify_chunk_type(chunk: str) -> ChunkType:
    """
    Classify a chunk of text into a ChunkType.
    Returns ChunkType.CONTENT as the default fallback.
    """
    text = chunk.strip()
    if not text:
        return ChunkType.CONTENT

    body = without_leading_heading(text)

    for rule in CHUNK_TYPE_RULES:
        if rule.matches(text, body):
            return rule.chunk_type

    return ChunkType.CONTENT