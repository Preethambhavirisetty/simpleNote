import logging
import time
import uuid
import re
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

    @staticmethod
    def _to_sparse_vector(sparse_emb) -> models.SparseVector:
        """Convert a fastembed/llama-index SparseEmbedding to a Qdrant SparseVector."""
        if isinstance(sparse_emb, dict):
            if "indices" in sparse_emb:
                indices = list(sparse_emb["indices"])
                values = list(sparse_emb["values"])
            else:
                indices = [int(k) for k in sparse_emb.keys()]
                values = [float(v) for v in sparse_emb.values()]
        else:
            indices = sparse_emb.indices.tolist() if hasattr(sparse_emb.indices, 'tolist') else list(sparse_emb.indices)
            values = sparse_emb.values.tolist() if hasattr(sparse_emb.values, 'tolist') else list(sparse_emb.values)
        return models.SparseVector(indices=indices, values=values)

    def _create_collection(self, name):
        sample = Settings.embed_model.get_text_embedding("dimension check")
        dim = len(sample)
        self._client.create_collection(
            collection_name=name,
            vectors_config={
                "dense": models.VectorParams(size=dim, distance=models.Distance.COSINE)
            },
            sparse_vectors_config={
                "sparse": models.SparseVectorParams(
                    modifier=models.Modifier.IDF,
                )
            },
        )
        log.info("Created Qdrant collection '%s' (dim=%d, sparse=IDF).", name, dim)

    def _ensure_collections(self):
        for name in (CHUNK_COLLECTION, SUMMARY_COLLECTION):
            if self._client.collection_exists(name):
                info = self._client.get_collection(name)
                vec_cfg = info.config.params.vectors
                if not isinstance(vec_cfg, dict):
                    log.warning(
                        "Collection '%s' uses old unnamed-vector schema. "
                        "Dropping and recreating. Re-ingest all notes.",
                        name,
                    )
                    self._client.delete_collection(name)
                    self._create_collection(name)
            else:
                self._create_collection(name)

    @staticmethod
    def _compute_quality_score(text: str, metadata: dict) -> float:
        """
        A robust, diverse quality scorer for RAG chunks.
        Combines: Structure (30%), Content/Length (40%), and Metadata (30%).
        """
        if not text or not text.strip():
            return 0.0

        # 1. STRUCTURE ANALYSIS (30%)
        lines = text.strip().splitlines()
        total_lines = len(lines)
        
        # Check for meaningful formatting
        headings = len(re.findall(r'^#+\s', text, re.MULTILINE))
        bullets = len(re.findall(r'^[\s]*[-*•]\s', text, re.MULTILINE))
        
        # Paragraph detection: Are there natural breaks or is it a "wall of text"?
        blank_lines = sum(1 for l in lines if not l.strip())
        # Ideal ratio is ~1 blank line per 5-7 lines of text
        para_score = 1.0 if (0.05 < (blank_lines / max(total_lines, 1)) < 0.25) else 0.5
        
        structure_score = (
            min(headings / 1, 1.0) * 0.4 +  # Even 1 heading is a great signal
            min(bullets / 3, 1.0) * 0.3 +   # 3+ bullets indicates a rich list
            para_score * 0.3
        )

        # 2. CONTENT & NOISE ANALYSIS (40%)
        words = text.split()
        wc = len(words)
        
        # Smooth Sigmoid-like Length Scoring (Penalty for <20 or >800 words)
        if wc < 20:
            length_factor = wc / 20 * 0.3  # Linear ramp up to 0.3
        elif 20 <= wc <= 600:
            length_factor = 1.0            # "Goldilocks" zone
        else:
            length_factor = max(0.4, 1.0 - (wc - 600) / 1000) # Gentle decay

        # Information Density: Unique words vs total words
        # Prevents repetitive "fluff" or keyword stuffing from scoring high
        unique_ratio = len(set(w.lower() for w in words)) / wc if wc > 0 else 0
        density_score = min(unique_ratio / 0.6, 1.0) # 60% unique is usually high-quality prose

        # Noise Check: Non-alphanumeric char ratio (filters out code junk/garbage)
        alnum_ratio = len(re.findall(r'\w', text)) / len(text) if len(text) > 0 else 0
        noise_penalty = 1.0 if alnum_ratio > 0.6 else alnum_ratio # Penalize if <60% text

        content_score = length_factor * 0.5 + density_score * 0.3 + noise_penalty * 0.2

        # 3. METADATA RICHNESS (30%)
        # Checks if the chunk is anchored to a source with valid context
        core_fields = ('note_title', 'folder_title', 'description', 'tags')
        valid_fields = sum(1 for f in core_fields if metadata.get(f) and str(metadata[f]).strip())
        meta_score = valid_fields / len(core_fields)

        # FINAL AGGREGATION
        final_score = (0.3 * structure_score) + (0.4 * content_score) + (0.3 * meta_score)
        
        return round(final_score, 3)


    def connect(self, embedder=None, persist_directory=None):
        self._client = QdrantClient(url=QDRANT_URL)
        self._ensure_collections()

    # ── Indexing ──────────────────────────────────────────────────────────

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

        print("***************** qdrant clean up completed! *****************")
        if summary_doc:
            dense_vec = Settings.embed_model.get_text_embedding(summary_doc.text)
            sparse_vec = self._to_sparse_vector(
                Settings.sparse_model.get_text_embedding(summary_doc.text)
            )
            s_doc_id = summary_doc.metadata.get("doc_id")
            if s_doc_id is None:
                raise ValueError("doc_id not found!")
            keywords = summary_doc.metadata.pop("keywords", [])
            entities = summary_doc.metadata.pop("entities", [])
            quality_score = self._compute_quality_score(
                summary_doc.text, summary_doc.metadata,
            )
            self._client.upsert(
                collection_name=SUMMARY_COLLECTION,
                points=[
                    models.PointStruct(
                        id=self._to_point_id(summary_doc.id_),
                        vector={"dense": dense_vec, "sparse": sparse_vec},
                        payload={
                            "doc_id": s_doc_id,
                            "text": summary_doc.text,
                            "keywords": keywords,
                            "entities": entities,
                            "created_at": int(time.time()),
                            "doc_quality": quality_score,
                            "is_high_quality": quality_score > 0.7,
                            "metadata": summary_doc.metadata or {},
                        },
                    )
                ],
            )
        print("***************** summary doc ingested! *****************")

        if chunk_docs:
            chunk_texts = [doc.text for doc in chunk_docs]
            dense_vecs = [
                Settings.embed_model.get_text_embedding(t) for t in chunk_texts
            ]
            sparse_vecs = [
                self._to_sparse_vector(
                    Settings.sparse_model.get_text_embedding(t)
                )
                for t in chunk_texts
            ]
            points = []
            for idx, (doc, dv, sv) in enumerate(
                zip(chunk_docs, dense_vecs, sparse_vecs)
            ):
                keywords = doc.metadata.pop("keywords", [])
                entities = doc.metadata.pop("entities", [])
                quality_score = self._compute_quality_score(
                    doc.text, doc.metadata,
                )
                points.append(
                    models.PointStruct(
                    id=self._to_point_id(doc.id_ or f"doc-{idx}"),
                    vector={"dense": dv, "sparse": sv},
                    payload={
                        "text": doc.text,
                        "keywords": keywords,
                        "entities": entities,
                        "created_at": int(time.time()),
                        "doc_quality": quality_score,
                        "is_high_quality": quality_score > 0.7,
                        "metadata": doc.metadata or {},
                    },
                )
                )
            self._client.upsert(collection_name=CHUNK_COLLECTION, points=points)
            print("***************** chunk docs ingested! *****************")

    # ── Retrieval ─────────────────────────────────────────────────────────

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
        """Dense-only search on summaries for doc-level scoping.

        Kept dense-only so cosine scores (0-1) remain compatible with the
        summary score thresholds used in VectorStore.retrieve_documents.
        """
        dense_vec = Settings.embed_model.get_query_embedding(query)
        qdrant_filter = self._build_qdrant_filter(filter)
        results = self._client.query_points(
            collection_name=SUMMARY_COLLECTION,
            query=dense_vec,
            using="dense",
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
        """Hybrid (dense + sparse RRF) search on chunks.

        Uses Qdrant-native prefetch to run dense and sparse searches
        server-side, then fuses results via Reciprocal Rank Fusion.
        """
        dense_vec = Settings.embed_model.get_query_embedding(query)
        sparse_vec = self._to_sparse_vector(
            Settings.sparse_model.get_query_embedding(query)
        )

        # build condition array + qdrant filter
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

        prefetch_limit = max(k * 2, 20)
        results = self._client.query_points(
            collection_name=CHUNK_COLLECTION,
            prefetch=[
                models.Prefetch(
                    query=dense_vec,
                    using="dense",
                    limit=prefetch_limit,
                ),
                models.Prefetch(
                    query=sparse_vec,
                    using="sparse",
                    limit=prefetch_limit,
                ),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=k,
            query_filter=qdrant_filter,
        ).points

        return [
            (
                LlamaDocument(
                    id_=str(point.id),
                    text=point.payload.get("text", ""),
                    metadata={
                        **point.payload.get("metadata", {}),
                        "keywords": point.payload.get("keywords", []),
                        "entities": point.payload.get("entities", []),
                        "doc_quality": point.payload.get("doc_quality", 0.0),
                    },
                ),
                point.score,
            )
            for point in results
        ]

    # ── Admin / maintenance ───────────────────────────────────────────────

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




""" sample points from qdrant after ingestion
summary point:
{"doc_id":"SAMPLEUSER01-SAMPLESFOLDER01-SAMPLENOTE01","text":"The text explores the challenges of aligning team tasks with document content, contrasted with excitement for the Pixel 8 Pro's technological advancements.","keywords":["management","organization","team","work","integration","report","strategy","operation","goals","language","validation phase","execution phase","analysis phase","review","metrics","workflow","system"],"entities":["Google Store","Mountain View","Apple A17 Pro","London","Marques Brownlee","Samsung S21"],"created_at":1774814905,"doc_quality":0.745,"is_high_quality":true,"metadata":{"doc_id":"SAMPLEUSER01-SAMPLESFOLDER01-SAMPLENOTE01","user_id":"SAMPLEUSER01","tenant_id":"TENANT01","folder_id":"SAMPLESFOLDER01","note_id":"SAMPLENOTE01","folder_title":"SAMPLE FOLDER TITLE1","note_title":"SAMPLE NOTE TITLE1","description":"SAMPLE DESCRIPTION 1","tags":"tag1,tag2","questions":["1. What are the specific challenges mentioned in the text regarding aligning team tasks with document content?","2. How does the text contrast the difficulties faced with team tasks and document content with the excitement for the Pixel 8 Pro's technological advancements?","3. Can you provide examples of the challenges described in the text related to aligning team tasks with document content?"]}}

chunk point:
{"text":"It says that the system should stabilize the system. These statements are grammatically valid but semantically weak. They create a worst-case scenario for a keyword extractor because the same words appear in many contexts, often without clear importance or hierarchy.","keywords":["system","statements","keyword extractor","contexts","importance or hierarchy","create","worst-case","words","case scenario"],"entities":[],"created_at":1774814908,"doc_quality":0.745,"is_high_quality":true,"metadata":{"doc_id":"SAMPLEUSER01-SAMPLESFOLDER01-SAMPLENOTE01","user_id":"SAMPLEUSER01","tenant_id":"TENANT01","folder_id":"SAMPLESFOLDER01","note_id":"SAMPLENOTE01","folder_title":"SAMPLE FOLDER TITLE1","note_title":"SAMPLE NOTE TITLE1","description":"SAMPLE DESCRIPTION 1","tags":"tag1,tag2","chunk_id":19,"parent_summary":"The text explores the challenges of aligning team tasks with document content, contrasted with excitement for the Pixel 8 Pro's technological advancements."}}
"""