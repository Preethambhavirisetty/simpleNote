"""Ingestion pipeline — extensible processing stages.

Stages:
    chunking    → text splitting and postprocessing
    keywords    → NLP keyword/entity extraction (spaCy + YAKE)
    enrichment  → LLM summarization, question generation, keyword dedup
    builder     → LlamaDocument assembly from pipeline outputs
    intent      → query intent detection (experimental)

Public API:
    get_document_objects(data) → (doc_id, summary_doc, chunk_docs)
"""

from pipeline.builder import get_document_objects

__all__ = ["get_document_objects"]
