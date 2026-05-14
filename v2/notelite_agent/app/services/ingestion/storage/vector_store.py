import logging
import time
import uuid
from collections.abc import Mapping, Sequence
from typing import Any, List

from llama_index.core import Document as LlamaDocument
from llama_index.core import Settings
from qdrant_client import models

from app.core.config import QDRANT_COLLECTION
from app.db.qdrant import QdrantClientManager


log = logging.getLogger(__name__)

CHUNK_COLLECTION = QDRANT_COLLECTION
SUMMARY_COLLECTION = f"{QDRANT_COLLECTION}_summaries"

DENSE_VECTOR = "dense"
SPARSE_VECTOR = "sparse"
QUESTIONS_VECTOR = "questions"

PAYLOAD_INDEXES = (
    ("metadata.user_id", models.PayloadSchemaType.KEYWORD),
    ("metadata.doc_id", models.PayloadSchemaType.KEYWORD),
)


class QdrantVectorStore:
    """Small Qdrant wrapper for vector storage and retrieval."""

    def __init__(self):
        self.client = QdrantClientManager.get_client()

    def ensure_collections(self) -> None:
        for collection_name in (CHUNK_COLLECTION, SUMMARY_COLLECTION):
            if not self._collection_exists(collection_name):
                self._create_collection(collection_name)
            self._ensure_payload_indexes(collection_name)

    def get_collections(self) -> List[str]:
        return self.client.get_collections()

    def _collection_exists(self, collection_name: str) -> bool:
        return bool(self.client and self.client.collection_exists(collection_name))

    def _embedding_dimension(self) -> int:
        if not getattr(Settings, "embed_model", None):
            raise RuntimeError("LlamaIndex settings must be initialized before Qdrant setup.")
        return len(Settings.embed_model.get_text_embedding("dimension check"))

    def _create_collection(self, collection_name: str) -> None:
        vector_size = self._embedding_dimension()
        vectors_config = {
            DENSE_VECTOR: models.VectorParams(
                size=vector_size,
                distance=models.Distance.COSINE,
            )
        }
        if collection_name == SUMMARY_COLLECTION:
            vectors_config[QUESTIONS_VECTOR] = models.VectorParams(
                size=vector_size,
                distance=models.Distance.COSINE,
            )

        self.client.create_collection(
            collection_name=collection_name,
            vectors_config=vectors_config,
            sparse_vectors_config={
                SPARSE_VECTOR: models.SparseVectorParams(modifier=models.Modifier.IDF),
            },
        )
        log.info("Created Qdrant collection %s with vector size %d", collection_name, vector_size)

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

        for collection_name in (CHUNK_COLLECTION, SUMMARY_COLLECTION):
            self.client.delete(
                collection_name=collection_name,
                points_selector=selector,
            )

    def upsert_summary(self, summary: LlamaDocument) -> None:
        metadata = dict(summary.metadata or {})
        keywords = list(metadata.pop("keywords", []))
        entities = list(metadata.pop("entities", []))
        questions = list(metadata.pop("questions", []))
        questions_text = " ".join(questions).strip()

        vectors = {
            DENSE_VECTOR: Settings.embed_model.get_text_embedding(summary.text),
            SPARSE_VECTOR: self.sparse_vector(Settings.sparse_model.get_text_embedding(summary.text)),
        }
        if questions_text:
            vectors[QUESTIONS_VECTOR] = Settings.embed_model.get_text_embedding(questions_text)

        self.client.upsert(
            collection_name=SUMMARY_COLLECTION,
            points=[
                models.PointStruct(
                    id=self.point_id(summary.id_),
                    vector=vectors,
                    payload={
                        "text": summary.text,
                        "keywords": keywords,
                        "entities": entities,
                        "questions": questions,
                        "created_at": int(time.time()),
                        "metadata": metadata,
                    },
                )
            ],
        )

    def upsert_chunks(self, chunks: Sequence[LlamaDocument]) -> None:
        if not chunks:
            return

        points = []
        for index, chunk in enumerate(chunks):
            metadata = dict(chunk.metadata or {})
            keywords = list(metadata.pop("keywords", []))
            entities = list(metadata.pop("entities", []))
            point_id = chunk.id_ or f"{metadata.get('doc_id', 'chunk')}-{index}"

            points.append(
                models.PointStruct(
                    id=self.point_id(point_id),
                    vector={
                        DENSE_VECTOR: Settings.embed_model.get_text_embedding(chunk.text),
                        SPARSE_VECTOR: self.sparse_vector(
                            Settings.sparse_model.get_text_embedding(chunk.text)
                        ),
                    },
                    payload={
                        "text": chunk.text,
                        "keywords": keywords,
                        "entities": entities,
                        "created_at": int(time.time()),
                        "metadata": metadata,
                    },
                )
            )

        self.client.upsert(collection_name=CHUNK_COLLECTION, points=points)

    def replace_document(
        self,
        doc_id: str,
        *,
        summary: LlamaDocument | None = None,
        chunks: Sequence[LlamaDocument] | None = None,
    ) -> None:
        self.delete_document(doc_id)
        if summary is not None:
            self.upsert_summary(summary)
        self.upsert_chunks(chunks or [])

    def search_chunks(
        self,
        query: str,
        *,
        limit: int = 10,
        metadata_filter: Mapping[str, Any] | None = None,
        doc_ids: Sequence[str] | None = None,
    ) -> list[tuple[LlamaDocument, float]]:
        dense_vector = Settings.embed_model.get_query_embedding(query)
        sparse_vector = self.sparse_vector(Settings.sparse_model.get_query_embedding(query))

        results = self.client.query_points(
            collection_name=CHUNK_COLLECTION,
            prefetch=[
                models.Prefetch(query=dense_vector, using=DENSE_VECTOR, limit=max(limit * 2, 20)),
                models.Prefetch(query=sparse_vector, using=SPARSE_VECTOR, limit=max(limit * 2, 20)),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=limit,
            query_filter=self.build_filter(metadata_filter, doc_ids),
        ).points

        return [self._point_to_document(point) for point in results]

    def search_summaries(
        self,
        query: str,
        *,
        limit: int = 10,
        metadata_filter: Mapping[str, Any] | None = None,
    ) -> list[tuple[LlamaDocument, float]]:
        results = self.client.query_points(
            collection_name=SUMMARY_COLLECTION,
            query=Settings.embed_model.get_query_embedding(query),
            using=DENSE_VECTOR,
            limit=limit,
            query_filter=self.build_filter(metadata_filter),
        ).points

        return [self._point_to_document(point) for point in results]

    @staticmethod
    def _point_to_document(point: Any) -> tuple[LlamaDocument, float]:
        payload = point.payload or {}
        metadata = dict(payload.get("metadata") or {})
        metadata.update(
            {
                "keywords": payload.get("keywords", []),
                "entities": payload.get("entities", []),
                "created_at": payload.get("created_at"),
            }
        )
        return (
            LlamaDocument(
                id_=str(point.id),
                text=payload.get("text", ""),
                metadata=metadata,
            ),
            point.score,
        )

    def scroll_chunks(self, collection_name:str, limit:int=10) -> list[LlamaDocument]:
        return self.client.scroll(
            collection_name=collection_name,
            limit=limit,
            with_payload=True,
            with_vectors=False
        )
        
