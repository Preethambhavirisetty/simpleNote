import hashlib
from typing import Sequence

from llama_index.core import Document

from app.services.ingestion.processors.keywords.keyword_processor import ChunkKeywordResult

_EXCLUDED_EMBED = ["user_id", "folder_id", "note_id", "chunk_id", "parent_summary"]
_EXCLUDED_LLM = ["user_id", "folder_id", "note_id", "chunk_id"]


class DocumentBuilder:
    def __init__(self):
        self.events = []
        self.api_calls = 0
        self.shared_metadata = {
            "excluded_embed_metadata_keys": _EXCLUDED_EMBED,
            "excluded_llm_metadata_keys": _EXCLUDED_LLM,
            "metadata_template": "{key}: {value}",
            "text_template": (
                "Context Information:\n{metadata_str}\n\n"
                "---\nDocument Content:\n{content}\n"
            ),
        }

    def build(self, **payload):
        self.events = ["documents build started"]
        note_summary = payload.get("note_summary") or ""
        summary_doc = (
            self.build_summary_doc(**payload)
            if note_summary.strip()
            else None
        )
        chunk_docs = self.build_chunk_docs(**payload)
        self.events.append(
            f"documents build completed: {1 if summary_doc else 0} summary, {len(chunk_docs)} chunks"
        )
        return summary_doc, chunk_docs

    def get_shared_payload(self, data: dict, doc_id: str) -> dict:
        raw_tags = data.get("tags") or []
        tags = raw_tags if isinstance(raw_tags, list) else [str(raw_tags)]
        return {
            "doc_id": doc_id,
            "user_id": data.get("user_id"),
            "folder_id": data.get("folder_id"),
            "note_id": data.get("note_id"),
            "folder_title": data.get("folder_title", ""),
            "note_title": data.get("note_title", ""),
            "description": data.get("description", ""),
            "tags": ",".join(str(tag) for tag in tags if str(tag).strip()),
        }

    def build_summary_doc(
        self,
        data: dict,
        doc_id: str,
        top_kw: Sequence[str],
        top_ent: Sequence[str],
        questions: Sequence[str],
        note_summary: str,
        **kwargs,
    ) -> Document:
        metadata = self.get_shared_payload(data, doc_id)
        metadata["keywords"] = list(top_kw or [])
        metadata["entities"] = list(top_ent or [])
        metadata["questions"] = list(questions or [])
        hashed_doc_id = hashlib.sha256(f"{doc_id}-summary".encode()).hexdigest()
        summary_doc = Document(
            id_=hashed_doc_id,
            text=note_summary,
            metadata=metadata,
            **self.shared_metadata
        )
        self.events.append("summary document built")
        return summary_doc

    def build_chunk_docs(
        self,
        data: dict,
        doc_id: str,
        chunk_objects: Sequence[ChunkKeywordResult],
        note_summary: str = "",
        **kwargs,
    ) -> list[Document]:
        chunk_docs = []

        for chunk in chunk_objects:
            metadata = self.get_shared_payload(data, doc_id)
            metadata["chunk_id"] = chunk.chunk_id
            metadata["keywords"] = chunk.keywords
            metadata["entities"] = chunk.entities
            if parent_summary := note_summary.strip():
                metadata["parent_summary"] = parent_summary
            chunk_doc = Document(
                id_=hashlib.sha256(f"{doc_id}-{chunk.chunk_id}".encode()).hexdigest(),
                text=chunk.content,
                metadata=metadata,
                **self.shared_metadata,
            )
            chunk_docs.append(chunk_doc)
        self.events.append(f"chunk documents built: {len(chunk_docs)}")
        return chunk_docs
