import logging
import uuid
from qdrant_client import QdrantClient, models
from llama_index.core import Document as LlamaDocument
from llama_index.core import Settings
from handlers.base import DBHandler
from core.config import QDRANT_COLLECTION, QDRANT_URL

log = logging.getLogger(__name__)

COLLECTION_NAME = QDRANT_COLLECTION

# Named-vector keys — every point stores two separate embeddings:
#   chunk_vec   → embedding of the raw chunk text
#   summary_vec → embedding of the Mistral-generated chunk summary
#                 (falls back to chunk text when Mistral is unavailable)
CHUNK_VEC   = "chunk_vec"
SUMMARY_VEC = "summary_vec"


class QdrantHandler(DBHandler):
    def __init__(self):
        self._client = None

    def _to_point_id(self, raw_id):
        try:
            return str(uuid.UUID(str(raw_id)))
        except (ValueError, TypeError):
            return str(uuid.uuid5(uuid.NAMESPACE_DNS, str(raw_id)))

    def _create_collection(self):
        """Create the collection with both named vector spaces."""
        sample = Settings.embed_model.get_text_embedding("dimension check")
        dim = len(sample)
        self._client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config={
                CHUNK_VEC:   models.VectorParams(size=dim, distance=models.Distance.COSINE),
                SUMMARY_VEC: models.VectorParams(size=dim, distance=models.Distance.COSINE),
            },
        )
        log.info("Created Qdrant collection '%s' with named vectors (dim=%d).", COLLECTION_NAME, dim)

    def _ensure_collection(self):
        if not self._client.collection_exists(COLLECTION_NAME):
            self._create_collection()
            return

        # Detect old single-vector schema and auto-migrate.
        # The old schema stores a single VectorParams object; the new schema stores a dict.
        info = self._client.get_collection(COLLECTION_NAME)
        vec_cfg = info.config.params.vectors
        if isinstance(vec_cfg, dict) and CHUNK_VEC in vec_cfg and SUMMARY_VEC in vec_cfg:
            return  # Already using named-vector schema

        log.warning(
            "Collection '%s' uses the old single-vector schema. "
            "Dropping and recreating with named vectors. Re-ingest all notes.",
            COLLECTION_NAME,
        )
        self._client.delete_collection(COLLECTION_NAME)
        self._create_collection()

    def connect(self, embedder=None, persist_directory=None):
        self._client = QdrantClient(url=QDRANT_URL)
        self._ensure_collection()

    def upsert(self, llama_docs, doc_id, persist_directory=None):
        self._client = QdrantClient(url=QDRANT_URL)
        self._ensure_collection()

        # Remove stale chunks for this document before re-inserting.
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

        chunk_texts   = [doc.text for doc in llama_docs]
        # Fall back to chunk text when Mistral summary is absent so the point is complete.
        summary_texts = [doc.metadata.get("summary") or doc.text for doc in llama_docs]

        chunk_vecs   = [Settings.embed_model.get_text_embedding(t) for t in chunk_texts]
        summary_vecs = [Settings.embed_model.get_text_embedding(s) for s in summary_texts]

        points = [
            models.PointStruct(
                id=self._to_point_id(doc.id_ or f"doc-{idx}"),
                vector={CHUNK_VEC: cv, SUMMARY_VEC: sv},
                payload={"text": doc.text, "metadata": doc.metadata or {}},
            )
            for idx, (doc, cv, sv) in enumerate(zip(llama_docs, chunk_vecs, summary_vecs))
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
        """Search both vector spaces and return a deduplicated union of results.

        Chunk-vector hits capture exact wording; summary-vector hits capture semantic
        intent even when a query uses different phrasing than the original text.
        """
        query_vector  = Settings.embed_model.get_query_embedding(query)
        qdrant_filter = self._build_qdrant_filter(filter)

        def _query(using):
            return self._client.query_points(
                collection_name=COLLECTION_NAME,
                query=query_vector,
                using=using,
                limit=k,
                query_filter=qdrant_filter,
            ).points

        chunk_hits   = _query(CHUNK_VEC)
        summary_hits = _query(SUMMARY_VEC)

        # Union: chunk hits are listed first (higher direct-match priority),
        # summary hits fill in anything not already captured.
        seen   = set()
        merged = []
        for point in chunk_hits + summary_hits:
            if point.id not in seen:
                seen.add(point.id)
                merged.append(
                    LlamaDocument(
                        id_=str(point.id),
                        text=point.payload.get("text", ""),
                        metadata=point.payload.get("metadata", {}),
                    )
                )
        return merged

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
