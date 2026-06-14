import hashlib
import re
from typing import Sequence

from llama_index.core import Document

from app.services.ingestion.processors.chunking.chunk_types import ChunkType
from app.services.ingestion.processors.chunking.token_budget import token_count
from app.services.ingestion.processors.keywords.keyword_processor import ChunkKeywordResult
from app.services.ingestion.processors.text_normalization import augment_markdown_table

_EXCLUDED_EMBED = ["user_id", "folder_id", "note_id", "chunk_id", "parent_summary"]
_EXCLUDED_LLM = ["user_id", "folder_id", "note_id", "chunk_id"]

INDEX_SKIP_REASONS: dict[str, str] = {}


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
        """Build a note summary document and ordered index-ready chunk artifacts.

        Input:
            data/doc_id plus ChunkKeywordResult objects and optional note-level summary data.

        Output:
            A summary Document and chunk Documents. Each chunk document carries content,
            embed_text, skip status, keywords/entities, ordering, adjacency, and metadata.
            Skipped artifacts are returned for observability but are filtered before indexing.
        """
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
        metadata["chunk_type"] = "summary"
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
        **kwargs,
    ) -> list[Document]:
        chunk_docs = []
        shared = self.get_shared_payload(data, doc_id)

        for index, chunk in enumerate(chunk_objects):
            metadata = {**shared, **chunk.metadata}
            metadata["chunk_id"] = chunk.chunk_id
            metadata["chunk_type"] = chunk.chunk_type
            metadata["chunk_index"] = chunk.chunk_index if chunk.total_chunks else index
            metadata["total_chunks"] = chunk.total_chunks or len(chunk_objects)
            metadata["keywords"] = chunk.keywords
            metadata["entities"] = chunk.entities
            metadata.setdefault("has_heading_context", bool(metadata.get("heading_context")))
            metadata.setdefault("token_count", token_count(chunk.content))
            metadata.setdefault("char_count", len(chunk.content))

            skip_reason = INDEX_SKIP_REASONS.get(chunk.chunk_type, "")
            metadata["skip_indexing"] = bool(skip_reason)
            metadata["skip_reason"] = skip_reason
            metadata["content"] = chunk.content
            metadata["embed_text"] = self._embedding_text(
                chunk.content,
                chunk.chunk_type,
                metadata.get("heading_context", ""),
            )

            chunk_docs.append(
                Document(
                    id_=self._chunk_document_id(doc_id, chunk.chunk_id),
                    text=metadata["embed_text"],
                    metadata=metadata,
                    **self.shared_metadata,
                )
            )

        indexable = [doc for doc in chunk_docs if not doc.metadata.get("skip_indexing")]
        for index, document in enumerate(indexable):
            if index > 0:
                document.metadata["prev_chunk_id"] = indexable[index - 1].metadata["chunk_id"]
            if index + 1 < len(indexable):
                document.metadata["next_chunk_id"] = indexable[index + 1].metadata["chunk_id"]

        skipped = len(chunk_docs) - len(indexable)
        self.events.append(f"chunk documents built: {len(chunk_docs)} ({len(indexable)} indexable)")
        if skipped:
            self.events.append(f"chunk documents skipped structural: {skipped}")
        return chunk_docs

    @staticmethod
    def _chunk_document_id(doc_id: str, chunk_id: str) -> str:
        return hashlib.sha256(f"{doc_id}-{chunk_id}".encode()).hexdigest()

    @staticmethod
    def _embedding_text(content: str, chunk_type: str, heading_context: str = "") -> str:
        if chunk_type == ChunkType.TABLE.value:
            table_summary = augment_markdown_table(content, heading_context)
            return f"{table_summary}\n\n{content}".strip() if table_summary else content

        body = DocumentBuilder._without_leading_headings(content)
        if heading_context and body:
            return f"{heading_context}\n\n{body}".strip()
        return body or content

    @staticmethod
    def _without_leading_headings(content: str) -> str:
        lines = content.splitlines()
        index = 0
        found_heading = False
        while index < len(lines):
            clean = lines[index].strip()
            if re.fullmatch(r"#{1,6}\s+\S[^\n]*", clean):
                found_heading = True
                index += 1
                continue
            if found_heading and not clean:
                index += 1
                continue
            break
        return "\n".join(lines[index:]).strip() if found_heading else content.strip()
