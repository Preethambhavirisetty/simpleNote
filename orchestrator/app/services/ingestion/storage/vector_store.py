from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
import uuid
from collections.abc import Mapping, Sequence
from typing import Any, List

from llama_index.core import Document as LlamaDocument
from llama_index.core import Settings
from qdrant_client import models

from app.core.config import QDRANT_COLLECTION
from app.services.ingestion.processors.ingest.models import IndexChunk, QuestionDocument, SummaryArtifacts, SummaryDocument
from app.db.qdrant import QdrantClientManager
from app.core.embeddings import (
    EmbeddingBatch,
    SharedEmbeddingClient,
)


log = logging.getLogger(__name__)

CHUNK_COLLECTION = QDRANT_COLLECTION
SUMMARY_COLLECTION = f"{QDRANT_COLLECTION}_summaries"
QUESTIONS_COLLECTION = f"{QDRANT_COLLECTION}_questions"

DENSE_VECTOR = "dense"
SPARSE_VECTOR = "sparse"
QUESTIONS_VECTOR = "questions"

PAYLOAD_INDEXES = (
    ("doc_id", models.PayloadSchemaType.KEYWORD),
    ("chunk_id", models.PayloadSchemaType.KEYWORD),
    ("metadata.user_id", models.PayloadSchemaType.KEYWORD),
    ("metadata.doc_id", models.PayloadSchemaType.KEYWORD),
)


class QdrantVectorStore:
    """Small Qdrant wrapper for vector storage and retrieval."""

    def __init__(self):
        self.client = QdrantClientManager.get_client()
        self.embedding_client = SharedEmbeddingClient()
        self.events = []

    def ensure_collections(self) -> None:
        for collection_name in (CHUNK_COLLECTION, SUMMARY_COLLECTION, QUESTIONS_COLLECTION):
            if not self._collection_exists(collection_name):
                self._create_collection(collection_name)
            self._ensure_payload_indexes(collection_name)

    def validate_collection_dimensions(self) -> None:
        expected = self._embedding_dimension()
        for name in (CHUNK_COLLECTION, SUMMARY_COLLECTION, QUESTIONS_COLLECTION):
            if not self._collection_exists(name): continue
            info = self.client.get_collection(name)
            vectors = info.config.params.vectors
            dense = vectors.get(DENSE_VECTOR) if isinstance(vectors, dict) else vectors
            if dense.size != expected:
                raise RuntimeError(f"Qdrant collection {name} dimension {dense.size} does not match embedding dimension {expected}")

    def get_collections(self) -> List[str]:
        return self.client.get_collections()

    def _collection_exists(self, collection_name: str) -> bool:
        return bool(self.client and self.client.collection_exists(collection_name))

    def _embedding_dimension(self) -> int:
        if not self.embedding_client.use_remote and not getattr(Settings, "embed_model", None):
            raise RuntimeError("LlamaIndex settings must be initialized before Qdrant setup.")
        dimension = self.embedding_client.dimension()
        self._drain_embedding_events()
        return dimension

    def _create_collection(self, collection_name: str) -> None:
        curr_vector_size = self._embedding_dimension()
        vectors_config = {
            DENSE_VECTOR: models.VectorParams(
                size=curr_vector_size,
                distance=models.Distance.COSINE,
            )
        }
        if collection_name == SUMMARY_COLLECTION:
            vectors_config[QUESTIONS_VECTOR] = models.VectorParams(
                size=curr_vector_size,
                distance=models.Distance.COSINE,
            )

        self.client.create_collection(
            collection_name=collection_name,
            vectors_config=vectors_config,
            sparse_vectors_config={
                SPARSE_VECTOR: models.SparseVectorParams(modifier=models.Modifier.IDF),
            },
        )
        self.events.append(f"Created Qdrant collection {collection_name} with vector size {curr_vector_size}")
        log.info("Created Qdrant collection %s with vector size %d", collection_name, curr_vector_size)

    def _ensure_payload_indexes(self, collection_name: str) -> None:
        for field_name, schema_type in PAYLOAD_INDEXES:
            try:
                self.client.create_payload_index(
                    collection_name=collection_name,
                    field_name=field_name,
                    field_schema=schema_type,
                )
            except Exception:
                log.debug("Payload index already exists or could not be created: %s", field_name)
                self.events.append(f"Payload index already exists or could not be created: {field_name}")
        self.events.append(
            f"payload indexes ensured: collection={collection_name} count={len(PAYLOAD_INDEXES)}"
        )

    @staticmethod
    def point_id(raw_id: Any) -> str:
        try:
            return str(uuid.UUID(str(raw_id)))
        except (TypeError, ValueError):
            return str(uuid.uuid5(uuid.NAMESPACE_DNS, str(raw_id)))

    @staticmethod
    def sparse_vector(sparse_embedding: Any) -> models.SparseVector:
        if isinstance(sparse_embedding, Mapping):
            if "indices" in sparse_embedding and "values" in sparse_embedding:
                indices = sparse_embedding["indices"]
                values = sparse_embedding["values"]
            else:
                indices = sparse_embedding.keys()
                values = sparse_embedding.values()
        else:
            indices = sparse_embedding.indices
            values = sparse_embedding.values

        if hasattr(indices, "tolist"):
            indices = indices.tolist()
        if hasattr(values, "tolist"):
            values = values.tolist()

        return models.SparseVector(
            indices=[int(index) for index in indices],
            values=[float(value) for value in values],
        )

    @staticmethod
    def build_filter(
        metadata_filter: Mapping[str, Any] | None = None,
        doc_ids: Sequence[str] | None = None,
    ) -> models.Filter | None:
        conditions = []

        for key, value in (metadata_filter or {}).items():
            conditions.append(
                models.FieldCondition(
                    key=f"metadata.{key}",
                    match=models.MatchValue(value=value),
                )
            )

        if doc_ids:
            conditions.append(
                models.FieldCondition(
                    key="metadata.doc_id",
                    match=models.MatchAny(any=list(doc_ids)),
                )
            )

        return models.Filter(must=conditions) if conditions else None

    def delete_document(self, doc_id: str) -> None:
        point_filter = self.build_filter({"doc_id": doc_id})
        selector = models.FilterSelector(filter=point_filter)

        for collection_name in (CHUNK_COLLECTION, SUMMARY_COLLECTION, QUESTIONS_COLLECTION):
            if not self._collection_exists(collection_name):
                log.info("Skipping Qdrant delete; collection does not exist: %s", collection_name)
                continue
            self.client.delete(
                collection_name=collection_name,
                points_selector=selector,
            )
        self.events.append(f"document vectors deleted: {doc_id}")

    def upsert_index_chunks(self, chunks: Sequence[IndexChunk]) -> None:
        """Embed and store application-owned index chunks."""
        indexable = [chunk for chunk in chunks if not chunk.skip_indexing]
        if not indexable:
            self.events.append("chunk vector upsert skipped: no indexable chunks")
            return

        embeddings = self.embed_texts([chunk.embed_text for chunk in indexable])
        indexed_at = datetime.now(timezone.utc).isoformat()
        embedding_model = self.embedding_client.remote_service.model
        points = []
        for index, chunk in enumerate(indexable):
            metadata = dict(chunk.metadata)
            metadata.update({
                "doc_id": chunk.document_id,
                "prev_chunk_id": chunk.prev_chunk_id,
                "next_chunk_id": chunk.next_chunk_id,
                "embedding_model": embedding_model,
                "embedding_dim": len(embeddings.dense[index]),
                "indexed_at": indexed_at,
            })
            points.append(models.PointStruct(
                id=self.point_id(f"{chunk.document_id}-{chunk.chunk_id}"),
                vector={
                    DENSE_VECTOR: embeddings.dense[index],
                    SPARSE_VECTOR: self.sparse_vector(embeddings.sparse[index]),
                },
                payload={
                    "doc_id": chunk.document_id, "chunk_id": chunk.chunk_id, "note_id": metadata.get("note_id", ""),
                    "folder_id": metadata.get("folder_id", ""), "chunk_index": chunk.chunk_index,
                    "total_chunks": chunk.total_chunks, "chunk_type": chunk.chunk_type,
                    "content": chunk.content, "embed_text": chunk.embed_text,
                    "skip_indexing": False, "skip_reason": "",
                    "keywords": chunk.keywords, "entities": chunk.entities,
                    "text": chunk.content, "created_at": int(time.time()), "metadata": metadata,
                },
            ))
        self.client.upsert(collection_name=CHUNK_COLLECTION, points=points)
        self.events.append(f"chunk vectors upserted: {len(points)}")
        skipped = len(chunks) - len(indexable)
        if skipped:
            self.events.append(f"chunk vectors skipped: {skipped}")

    def upsert_summary_artifacts(self, artifacts: SummaryArtifacts) -> None:
        """Embed and store application-owned summary and question artifacts."""
        if artifacts.summary is not None:
            summary = artifacts.summary
            embeddings = self.embed_texts([summary.embed_text])
            self.client.upsert(collection_name=SUMMARY_COLLECTION, points=[models.PointStruct(
                id=self.point_id(summary.summary_id),
                vector={DENSE_VECTOR: embeddings.dense[0], SPARSE_VECTOR: self.sparse_vector(embeddings.sparse[0])},
                payload={
                    "text": summary.content, "content": summary.content, "embed_text": summary.embed_text,
                    "keywords": summary.keywords, "entities": summary.entities,
                    "created_at": int(time.time()), "metadata": summary.metadata,
                },
            )])
            self.events.append("summary vector upserted")
        if artifacts.questions:
            embeddings = self.embed_texts([question.embed_text for question in artifacts.questions])
            points = [models.PointStruct(
                id=self.point_id(question.question_id),
                vector={DENSE_VECTOR: embeddings.dense[index], SPARSE_VECTOR: self.sparse_vector(embeddings.sparse[index])},
                payload={
                    "text": question.content, "content": question.content, "embed_text": question.embed_text,
                    "created_at": int(time.time()), "metadata": question.metadata,
                },
            ) for index, question in enumerate(artifacts.questions)]
            self.client.upsert(collection_name=QUESTIONS_COLLECTION, points=points)
            self.events.append(f"question vectors upserted: {len(points)}")

    def replace_index_chunks(self, doc_id: str, chunks: Sequence[IndexChunk]) -> None:
        self.events = ["chunk vector ingestion started"]
        self.ensure_collections()
        self.delete_document(doc_id)
        self.upsert_index_chunks(chunks)
        self.events.append("chunk vector ingestion completed")

    @staticmethod
    def build_identity_filter(
        identities: Sequence[tuple[str, str]] | None,
    ) -> models.Filter | None:
        if not identities:
            return None

        identity_filters = []
        for doc_id, chunk_id in identities:
            conditions = [
                models.FieldCondition(
                    key="doc_id",
                    match=models.MatchValue(value=doc_id),
                )
            ]
            if chunk_id != "*":
                conditions.append(
                    models.FieldCondition(
                        key="chunk_id",
                        match=models.MatchValue(value=chunk_id),
                    )
                )
            identity_filters.append(models.Filter(must=conditions))
        return models.Filter(should=identity_filters)

    def _search_vector(
        self,
        collection_name: str,
        vector: Any,
        vector_name: str,
        *,
        limit: int,
        metadata_filter: Mapping[str, Any] | None = None,
        doc_ids: Sequence[str] | None = None,
        identities: Sequence[tuple[str, str]] | None = None,
    ) -> list[tuple[LlamaDocument, float]]:
        metadata_query_filter = self.build_filter(metadata_filter, doc_ids)
        identity_query_filter = self.build_identity_filter(identities)
        query_filter = self._combine_filters(metadata_query_filter, identity_query_filter)

        points = self.client.query_points(
            collection_name=collection_name,
            query=vector,
            using=vector_name,
            limit=limit,
            query_filter=query_filter,
        ).points
        return [self._point_to_document(point) for point in points]

    @staticmethod
    def _combine_filters(*filters: models.Filter | None) -> models.Filter | None:
        active_filters = [query_filter for query_filter in filters if query_filter is not None]
        if not active_filters:
            return None
        if len(active_filters) == 1:
            return active_filters[0]
        return models.Filter(must=active_filters)

    def search_chunk_dense(self, vector: list[float], **kwargs) -> list[tuple[LlamaDocument, float]]:
        return self._search_vector(CHUNK_COLLECTION, vector, DENSE_VECTOR, **kwargs)

    def search_chunk_sparse(self, vector: Any, **kwargs) -> list[tuple[LlamaDocument, float]]:
        return self._search_vector(
            CHUNK_COLLECTION,
            self.sparse_vector(vector),
            SPARSE_VECTOR,
            **kwargs,
        )

    def search_summary_dense(self, vector: list[float], **kwargs) -> list[tuple[LlamaDocument, float]]:
        return self._search_vector(SUMMARY_COLLECTION, vector, DENSE_VECTOR, **kwargs)

    def search_question_dense(self, vector: list[float], **kwargs) -> list[tuple[LlamaDocument, float]]:
        return self._search_vector(QUESTIONS_COLLECTION, vector, DENSE_VECTOR, **kwargs)

    def fetch_neighbor(self, doc_id: str | None, chunk_id: str | None) -> LlamaDocument | None:
        if not doc_id or not chunk_id:
            return None

        points, _next_page = self.client.scroll(
            collection_name=CHUNK_COLLECTION,
            scroll_filter=models.Filter(must=[
                models.FieldCondition(
                    key="doc_id",
                    match=models.MatchValue(value=str(doc_id)),
                ),
                models.FieldCondition(
                    key="chunk_id",
                    match=models.MatchValue(value=str(chunk_id)),
                ),
            ]),
            limit=1,
            with_payload=True,
            with_vectors=False,
        )
        if not points:
            return None
        return self._point_to_document(points[0])[0]

    def embed_texts(self, texts: Sequence[str]) -> EmbeddingBatch:
        embeddings = self.embedding_client.embed_documents(texts)
        self._drain_embedding_events()
        return embeddings

    def embed_dense_texts(self, texts: Sequence[str]) -> list[list[float]]:
        embeddings = self.embedding_client.embed_dense_documents(texts)
        self._drain_embedding_events()
        return embeddings

    def embed_query_texts(self, texts: Sequence[str]) -> EmbeddingBatch:
        embeddings = self.embedding_client.embed_queries(texts)
        self._drain_embedding_events()
        return embeddings

    def embed_dense_queries(self, texts: Sequence[str]) -> list[list[float]]:
        embeddings = self.embedding_client.embed_dense_queries(texts)
        self._drain_embedding_events()
        return embeddings

    def _drain_embedding_events(self) -> None:
        self.events.extend(self.embedding_client.events)
        self.embedding_client.events = []

    @staticmethod
    def _point_to_document(point: Any) -> tuple[LlamaDocument, float]:
        payload = point.payload or {}
        metadata = dict(payload.get("metadata") or {})
        metadata.update(
            {
                "doc_id": payload.get("doc_id", metadata.get("doc_id")),
                "chunk_id": payload.get("chunk_id", metadata.get("chunk_id")),
                "prev_chunk_id": payload.get("prev_chunk_id", metadata.get("prev_chunk_id")),
                "next_chunk_id": payload.get("next_chunk_id", metadata.get("next_chunk_id")),
                "note_id": payload.get("note_id", metadata.get("note_id")),
                "folder_id": payload.get("folder_id", metadata.get("folder_id")),
                "chunk_index": payload.get("chunk_index", metadata.get("chunk_index")),
                "total_chunks": payload.get("total_chunks", metadata.get("total_chunks")),
                "chunk_type": payload.get("chunk_type", metadata.get("chunk_type")),
                "keywords": payload.get("keywords", []),
                "entities": payload.get("entities", []),
                "created_at": payload.get("created_at"),
            }
        )
        return (
            LlamaDocument(
                id_=str(point.id),
                text=payload.get("content", payload.get("text", "")),
                metadata=metadata,
            ),
            float(getattr(point, "score", 0.0)),
        )

    def scroll_chunks(self, collection_name:str, limit:int=10) -> list[LlamaDocument]:
        return self.client.scroll(
            collection_name=collection_name,
            limit=limit,
            with_payload=True,
            with_vectors=False
        )
        
