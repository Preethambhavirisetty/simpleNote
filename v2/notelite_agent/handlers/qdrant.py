import uuid
from qdrant_client import QdrantClient, models
from llama_index.core import Document as LlamaDocument
from llama_index.core import Settings
from handlers.base import DBHandler
from core.config import QDRANT_COLLECTION

COLLECTION_NAME = QDRANT_COLLECTION


class QdrantHandler(DBHandler):
    def __init__(self):
        self._client = None

    def _to_point_id(self, raw_id):
        try:
            return str(uuid.UUID(str(raw_id)))
        except (ValueError, TypeError):
            return str(uuid.uuid5(uuid.NAMESPACE_DNS, str(raw_id)))

    def _ensure_collection(self):
        if self._client.collection_exists(COLLECTION_NAME):
            return
        sample_vec = Settings.embed_model.get_text_embedding("dimension check")
        self._client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=models.VectorParams(
                size=len(sample_vec),
                distance=models.Distance.COSINE,
            ),
        )

    def connect(self, embedder, persist_directory):
        self._client = QdrantClient(path=persist_directory)
        self._ensure_collection()

    def upsert(self, llama_docs, doc_id, persist_directory):
        self._client = QdrantClient(path=persist_directory)
        self._ensure_collection()
        # If doc_id exists, delete all prior chunks first to avoid stale retrieval.
        doc_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="metadata.doc_id",
                    match=models.MatchValue(value=doc_id),
                )
            ]
        )
        self._client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=models.FilterSelector(filter=doc_filter),
        )

        texts = [doc.text for doc in llama_docs]
        vectors = [Settings.embed_model.get_text_embedding(text) for text in texts]
        points = [
            models.PointStruct(
                id=self._to_point_id(doc.id_ or f"doc-{idx}"),
                vector=vector,
                payload={
                    "text": doc.text,
                    "metadata": doc.metadata or {},
                },
            )
            for idx, (doc, vector) in enumerate(zip(llama_docs, vectors))
        ]
        self._client.upsert(collection_name=COLLECTION_NAME, points=points)

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

    def search(self, query, k, filter=None):
        query_vector = Settings.embed_model.get_query_embedding(query)
        qdrant_filter = self._build_qdrant_filter(filter)

        results = self._client.query_points(
            collection_name=COLLECTION_NAME,
            query=query_vector,
            limit=k,
            query_filter=qdrant_filter,
        )

        return [
            LlamaDocument(
                id_=str(point.id),
                text=point.payload.get("text", ""),
                metadata=point.payload.get("metadata", {}),
            )
            for point in results.points
        ]

    def count(self, filter=None):
        qdrant_filter = self._build_qdrant_filter(filter)
        return self._client.count(
            collection_name=COLLECTION_NAME,
            count_filter=qdrant_filter,
            exact=True,
        ).count

    def get_all_documents(self, filter=None):
        all_docs = []
        offset = None
        qdrant_filter = self._build_qdrant_filter(filter)
        while True:
            results, offset = self._client.scroll(
                collection_name=COLLECTION_NAME,
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
            collection_name=COLLECTION_NAME,
            points_selector=models.FilterSelector(filter=qdrant_filter),
        )

    def close(self):
        if self._client:
            self._client.close()
            self._client = None
