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
        vectors = {
            "dense": models.VectorParams(size=dim, distance=models.Distance.COSINE),
        }
        if name == SUMMARY_COLLECTION:
            vectors["questions"] = models.VectorParams(size=dim, distance=models.Distance.COSINE)
        self._client.create_collection(
            collection_name=name,
            vectors_config=vectors,
            sparse_vectors_config={
                "sparse": models.SparseVectorParams(
                    modifier=models.Modifier.IDF,
                )
            },
        )
        log.info("Created Qdrant collection '%s' (dim=%d, sparse=IDF).", name, dim)

    _PAYLOAD_INDEXES = [
        ("metadata.user_id", models.PayloadSchemaType.KEYWORD),
        ("metadata.tenant_id", models.PayloadSchemaType.KEYWORD),
        ("metadata.doc_id", models.PayloadSchemaType.KEYWORD),
    ]

    def _ensure_payload_indexes(self, collection_name):
        """Create payload indexes if they don't already exist"""
        for field, schema_type in self._PAYLOAD_INDEXES:
            try:
                self._client.create_payload_index(
                    collection_name=collection_name,
                    field_name=field,
                    field_schema=schema_type,
                )
            except Exception:
                pass

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
            self._ensure_payload_indexes(name)

    @staticmethod
    def _compute_quality_score(
        text: str,
        metadata: dict,
        keywords: list | None = None,
        entities: list | None = None,
    ) -> float:
        """Quality scorer for RAG chunks.

        Weights: Structure 20%, Content 30%, Information Richness 30%, Metadata 20%.

        Information Richness uses per-chunk keyword/entity counts so that
        chunks with more extractable concepts score higher than ones with
        generic prose, giving meaningful differentiation across chunks of
        the same note.
        """
        if not text or not text.strip():
            return 0.0

        keywords = keywords or []
        entities = entities or []

        # ── 1. STRUCTURE (20%) ────────────────────────────────────────
        lines = text.strip().splitlines()
        total_lines = len(lines)

        headings = len(re.findall(r'^#+\s', text, re.MULTILINE))
        bullets = len(re.findall(r'^[\s]*[-*•]\s', text, re.MULTILINE))

        blank_lines = sum(1 for l in lines if not l.strip())
        bl_ratio = blank_lines / max(total_lines, 1)
        para_score = 1.0 if 0.05 < bl_ratio < 0.25 else 0.5

        structure_score = (
            min(headings, 2) / 2 * 0.4
            + min(bullets / 3, 1.0) * 0.3
            + para_score * 0.3
        )

        # ── 2. CONTENT & DENSITY (30%) ───────────────────────────────
        words = text.split()
        wc = len(words)

        # Peaked length curve: best at 100-400 words, tapers outside
        if wc < 20:
            length_factor = wc / 20 * 0.3
        elif wc < 80:
            length_factor = 0.6 + 0.4 * ((wc - 20) / 60)
        elif wc <= 400:
            length_factor = 1.0
        elif wc <= 600:
            length_factor = 1.0 - 0.2 * ((wc - 400) / 200)
        else:
            length_factor = max(0.4, 0.8 - (wc - 600) / 1000)

        lower_words = [w.lower() for w in words]
        unique_ratio = len(set(lower_words)) / wc if wc > 0 else 0
        density_score = min(unique_ratio / 0.55, 1.0)

        alnum_chars = sum(c.isalnum() for c in text)
        alnum_ratio = alnum_chars / len(text) if text else 0
        noise_penalty = 1.0 if alnum_ratio > 0.6 else alnum_ratio

        # Average sentence length variance (signals well-structured writing)
        sentences = re.split(r'[.!?]+', text)
        sentences = [s.strip() for s in sentences if s.strip()]
        if len(sentences) >= 2:
            sent_lens = [len(s.split()) for s in sentences]
            mean_sl = sum(sent_lens) / len(sent_lens)
            variance = sum((l - mean_sl) ** 2 for l in sent_lens) / len(sent_lens)
            # Moderate variance (not all same length, not wildly uneven) is best
            std_dev = variance ** 0.5
            sent_variety = min(std_dev / 8.0, 1.0)
        else:
            sent_variety = 0.3

        content_score = (
            length_factor * 0.35
            + density_score * 0.30
            + noise_penalty * 0.15
            + sent_variety * 0.20
        )

        # ── 3. INFORMATION RICHNESS (30%) ────────────────────────────
        # Per-chunk keywords and entities -- the primary differentiator
        kw_count = len(keywords)
        ent_count = len(entities)

        kw_score = min(kw_count / 8.0, 1.0)
        ent_score = min(ent_count / 3.0, 1.0)

        # Proper nouns (capitalized words not at sentence start) as a proxy
        # for domain specificity when entity extraction is sparse
        propn_count = sum(
            1 for i, w in enumerate(words)
            if w[0].isupper() and i > 0 and not words[i - 1].endswith(('.', '!', '?'))
        )
        propn_score = min(propn_count / 6.0, 1.0)

        info_score = kw_score * 0.50 + ent_score * 0.30 + propn_score * 0.20

        # ── 4. METADATA COMPLETENESS (20%) ───────────────────────────
        core_fields = ('note_title', 'folder_title', 'description', 'tags')
        valid_fields = sum(
            1 for f in core_fields
            if metadata.get(f) and str(metadata[f]).strip()
        )
        meta_score = valid_fields / len(core_fields)

        # ── FINAL ────────────────────────────────────────────────────
        final_score = (
            0.20 * structure_score
            + 0.30 * content_score
            + 0.30 * info_score
            + 0.20 * meta_score
        )

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
            questions = summary_doc.metadata.pop("questions", [])
            quality_score = self._compute_quality_score(
                summary_doc.text, summary_doc.metadata,
                keywords=keywords, entities=entities,
            )

            vectors = {"dense": dense_vec, "sparse": sparse_vec}
            questions_text = " ".join(questions).strip()
            if questions_text:
                vectors["questions"] = Settings.embed_model.get_text_embedding(questions_text)

            self._client.upsert(
                collection_name=SUMMARY_COLLECTION,
                points=[
                    models.PointStruct(
                        id=self._to_point_id(summary_doc.id_),
                        vector=vectors,
                        payload={
                            "doc_id": s_doc_id,
                            "text": summary_doc.text,
                            "keywords": keywords,
                            "entities": entities,
                            "questions": questions,
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
                    keywords=keywords, entities=entities,
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

    def search_summaries(
        self,
        query,
        k,
        filter=None,
        *,
        questions_weight: float = 0.6,
        summary_weight: float = 0.4,
    ):
        """Two-vector search on summaries: dense (summary text) + questions.

        Runs both queries, merges by weighted score:
            final = questions_weight * q_score + summary_weight * s_score

        Falls back to dense-only when a point has no questions vector.
        """
        dense_vec = Settings.embed_model.get_query_embedding(query)
        qdrant_filter = self._build_qdrant_filter(filter)
        fetch_limit = max(k * 3, 20)

        summary_results = self._client.query_points(
            collection_name=SUMMARY_COLLECTION,
            query=dense_vec,
            using="dense",
            limit=fetch_limit,
            query_filter=qdrant_filter,
        ).points

        questions_results = self._client.query_points(
            collection_name=SUMMARY_COLLECTION,
            query=dense_vec,
            using="questions",
            limit=fetch_limit,
            query_filter=qdrant_filter,
        ).points

        q_scores = {str(p.id): p.score for p in questions_results}
        s_scores = {str(p.id): p.score for p in summary_results}

        all_points = {}
        for p in summary_results:
            all_points[str(p.id)] = p
        for p in questions_results:
            pid = str(p.id)
            if pid not in all_points:
                all_points[pid] = p

        scored = []
        for pid, point in all_points.items():
            s_score = s_scores.get(pid, 0.0)
            q_score = q_scores.get(pid)

            if q_score is not None:
                final = questions_weight * q_score + summary_weight * s_score
            else:
                final = s_score

            scored.append((point, final))

        scored.sort(key=lambda x: x[1], reverse=True)

        return [
            (
                LlamaDocument(
                    id_=str(point.id),
                    text=point.payload.get("text", ""),
                    metadata=point.payload.get("metadata", {}),
                ),
                score,
            )
            for point, score in scored[:k]
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

    def scroll_chunks(self, filter=None):
        """Paginated scroll returning all chunks matching *filter* (text + metadata only)."""
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
                        metadata={
                            **point.payload.get("metadata", {}),
                            "created_at": point.payload.get("created_at"),
                        },
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