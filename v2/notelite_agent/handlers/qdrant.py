import logging
import uuid
from qdrant_client import QdrantClient, models
from llama_index.core import Document as LlamaDocument
from llama_index.core import Settings
from handlers.base import DBHandler
from core.config import QDRANT_COLLECTION, QDRANT_URL

log = logging.getLogger(__name__)

CHUNK_COLLECTION = QDRANT_COLLECTION
SUMMARY_COLLECTION = f"{QDRANT_COLLECTION}_summaries"


class QdrantHandler(DBHandler):
    def __init__(self):
        self._client = None

    def _to_point_id(self, raw_id):
        try:
            return str(uuid.UUID(str(raw_id)))
        except (ValueError, TypeError):
            return str(uuid.uuid5(uuid.NAMESPACE_DNS, str(raw_id)))

    def _create_collection(self, name):
        sample = Settings.embed_model.get_text_embedding("dimension check")
        dim = len(sample)
        self._client.create_collection(
            collection_name=name,
            vectors_config={
                "dense": models.VectorParams(size=dim, distance=models.Distance.COSINE)
            },
            sparse_vectors_config={
                "sparse": {}
            }
        )
        log.info("Created Qdrant collection '%s' (dim=%d).", name, dim)

    def _ensure_collections(self):
        if self._client.collection_exists(CHUNK_COLLECTION):
            info = self._client.get_collection(CHUNK_COLLECTION)
            vec_cfg = info.config.params.vectors
            if isinstance(vec_cfg, dict):
                log.warning(
                    "Collection '%s' uses old named-vector schema. "
                    "Dropping and recreating. Re-ingest all notes.",
                    CHUNK_COLLECTION,
                )
                self._client.delete_collection(CHUNK_COLLECTION)
                self._create_collection(CHUNK_COLLECTION)
        else:
            self._create_collection(CHUNK_COLLECTION)

        if not self._client.collection_exists(SUMMARY_COLLECTION):
            self._create_collection(SUMMARY_COLLECTION)

    def connect(self, embedder=None, persist_directory=None):
        self._client = QdrantClient(url=QDRANT_URL)
        self._ensure_collections()

    def upsert(self, summary_doc, chunk_docs, doc_id, persist_directory=None):
        self._client = QdrantClient(url=QDRANT_URL)
        self._ensure_collections()

        doc_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="metadata.doc_id",
                    match=models.MatchValue(value=doc_id),
                )
            ]
        )

        self._client.delete(
            collection_name=CHUNK_COLLECTION,
            points_selector=models.FilterSelector(filter=doc_filter),
        )
        self._client.delete(
            collection_name=SUMMARY_COLLECTION,
            points_selector=models.FilterSelector(filter=doc_filter),
        )

        if summary_doc:
            summary_vec = Settings.embed_model.get_text_embedding(summary_doc.text)
            doc_id = summary_doc.metadata.get("doc_id")
            if doc_id is None:
                raise ValueError("doc_id not found!")
            keywords = summary_doc.metadata.get("keywords", [])
            entities = summary_doc.metadata.get("entities", [])
            self._client.upsert(
                collection_name=SUMMARY_COLLECTION,
                points=[
                    models.PointStruct(
                        id=self._to_point_id(summary_doc.id_),
                        vector=summary_vec,
                        payload={
                            "doc_id": doc_id,
                            "text": summary_doc.text,
                            "keywords": keywords,
                            "entities": entities,
                            "metadata": summary_doc.metadata or {},
                        },
                    )
                ],
            )

        if chunk_docs:
            chunk_texts = [doc.text for doc in chunk_docs]
            chunk_vecs = [
                Settings.embed_model.get_text_embedding(t) for t in chunk_texts
            ]
            points = [
                models.PointStruct(
                    id=self._to_point_id(doc.id_ or f"doc-{idx}"),
                    vector=cv,
                    payload={
                        "text": doc.text,
                        "keywords": doc.metadata.pop("keywords") if "keywords" in doc.metadata else [],
                        "entities": doc.metadata.pop("entities") if "entities" in doc.metadata else [],
                        "metadata": doc.metadata or {}
                    },
                )
                for idx, (doc, cv) in enumerate(zip(chunk_docs, chunk_vecs))
            ]
            self._client.upsert(collection_name=CHUNK_COLLECTION, points=points)

    def _build_qdrant_filter(self, filter=None):
        if not filter:
            return None
        conditions = [
            models.FieldCondition(
                key=f"metadata.{key}",
                match=models.MatchValue(value=value),
            )
            for key, value in filter.items()
        ]
        return models.Filter(must=conditions)

    def search_summaries(self, query, k, filter=None):
        """Search doc_summaries collection, return [(LlamaDocument, score), ...]."""
        query_vector = Settings.embed_model.get_query_embedding(query)
        qdrant_filter = self._build_qdrant_filter(filter)
        results = self._client.query_points(
            collection_name=SUMMARY_COLLECTION,
            query=query_vector,
            limit=k,
            query_filter=qdrant_filter,
        ).points
        return [
            (
                LlamaDocument(
                    id_=str(point.id),
                    text=point.payload.get("text", ""),
                    metadata=point.payload.get("metadata", {}),
                ),
                point.score,
            )
            for point in results
        ]

    def search(self, query, k, filter=None, doc_ids=None):
        """Search doc_chunks collection, optionally scoped to specific doc_ids."""
        query_vector = Settings.embed_model.get_query_embedding(query)
        conditions = []
        if filter:
            for key, value in filter.items():
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
                    match=models.MatchAny(any=doc_ids),
                )
            )
        qdrant_filter = models.Filter(must=conditions) if conditions else None
        results = self._client.query_points(
            collection_name=CHUNK_COLLECTION,
            query=query_vector,
            limit=k,
            query_filter=qdrant_filter,
        ).points
        return [
            LlamaDocument(
                id_=str(point.id),
                text=point.payload.get("text", ""),
                metadata=point.payload.get("metadata", {}),
            )
            for point in results
        ]

    def count(self, filter=None):
        qdrant_filter = self._build_qdrant_filter(filter)
        return self._client.count(
            collection_name=CHUNK_COLLECTION,
            count_filter=qdrant_filter,
            exact=True,
        ).count

    def get_all_documents(self, filter=None):
        all_docs = []
        offset = None
        qdrant_filter = self._build_qdrant_filter(filter)
        while True:
            results, offset = self._client.scroll(
                collection_name=CHUNK_COLLECTION,
                limit=100,
                offset=offset,
                scroll_filter=qdrant_filter,
                with_payload=True,
                with_vectors=False,
            )
            for point in results:
                all_docs.append(
                    LlamaDocument(
                        id_=str(point.id),
                        text=point.payload.get("text", ""),
                        metadata=point.payload.get("metadata", {}),
                    )
                )
            if offset is None:
                break
        return all_docs

    def delete(self, filter=None):
        if not filter:
            return
        qdrant_filter = self._build_qdrant_filter(filter)
        if not qdrant_filter:
            return
        self._client.delete(
            collection_name=CHUNK_COLLECTION,
            points_selector=models.FilterSelector(filter=qdrant_filter),
        )
        if self._client.collection_exists(SUMMARY_COLLECTION):
            self._client.delete(
                collection_name=SUMMARY_COLLECTION,
                points_selector=models.FilterSelector(filter=qdrant_filter),
            )

    def close(self):
        if self._client:
            self._client.close()
            self._client = None
