import os
import shutil
import sys
import importlib
from rank_bm25 import BM25Okapi
from core.config import DB_PATH, VECTOR_DB, RERANKER_MODEL, QDRANT_URL
from core.contracts import AccessContext
from core.settings import is_llama_index_settings_initialized
from llama_index.core import Settings


_SUMMARY_SCORE_HIGH = 0.8
_SUMMARY_SCORE_LOW = 0.7
_SCORE_GAP_THRESHOLD = 0.05
_MAX_FILTERED_DOCS = 3


class VectorStore:
    def __init__(self, persist_directory=DB_PATH):
        self._persist_directory = persist_directory
        if not is_llama_index_settings_initialized():
            raise RuntimeError(
                "LlamaIndex settings are not initialized. "
                "Call init_llama_index_settings() once at application startup."
            )
        self._embedder = Settings.embed_model
        self._reranker = None

        self._handler = self._load_handler(VECTOR_DB)

        self._bm25 = None
        self._bm25_docs = []
        self._connected = False

    @property
    def embedder(self):
        return self._embedder

    # ------ HELPERS METHODS ------------------------------------

    @staticmethod
    def _load_handler(vector_db_name):
        """
        Load handler factory robustly across runtime contexts
        (uvicorn, celery worker, tests, different cwd/PYTHONPATH).
        """
        module_candidates = ["handlers", "rag.handlers"]
        for module_name in module_candidates:
            try:
                module = importlib.import_module(module_name)
                return module.get_handler(vector_db_name)
            except ModuleNotFoundError:
                continue

        # Try repairing import path dynamically based on file location.
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        project_parent = os.path.abspath(os.path.join(project_root, ".."))
        for candidate in (project_root, project_parent):
            if candidate not in sys.path:
                sys.path.insert(0, candidate)

        for module_name in module_candidates:
            try:
                module = importlib.import_module(module_name)
                return module.get_handler(vector_db_name)
            except ModuleNotFoundError:
                continue

        raise ModuleNotFoundError(
            "Could not import handler module. Ensure project root is on PYTHONPATH."
        )

    def _resolve_scope_filter(self, access_context, filter=None):
        return access_context.apply_scope(filter)

    def _is_backend_reachable(self) -> bool:
        """Return True when a Qdrant server URL is configured or a local store exists."""
        return bool(QDRANT_URL) or os.path.exists(self._persist_directory)

    def _build_bm25_index(self, documents):
        if not documents:
            self._bm25 = None
            self._bm25_docs = []
            return
        self._bm25_docs = documents
        tokenized = [doc.text.lower().split() for doc in documents]
        self._bm25 = BM25Okapi(tokenized)

    def _ensure_connected(self):
        if not self._connected:
            if self._is_backend_reachable():
                self.connect()
            else:
                raise RuntimeError("No vector store found. Call load() to ingest documents first.")

    def _bm25_search(self, query, k, filter=None, doc_ids=None):
        if not self._bm25:
            return []
        tokens = query.lower().split()
        scores = self._bm25.get_scores(tokens)

        indices = range(len(scores))
        if filter:
            indices = [
                i for i in indices
                if all(self._bm25_docs[i].metadata.get(key) == val for key, val in filter.items())
            ]
        if doc_ids:
            doc_ids_set = set(doc_ids)
            indices = [
                i for i in indices
                if self._bm25_docs[i].metadata.get("doc_id") in doc_ids_set
            ]

        top = sorted(indices, key=lambda i: scores[i], reverse=True)[:k]
        return [self._bm25_docs[i] for i in top if scores[i] > 0]

    @staticmethod
    def _rrf_fusion(semantic_results, lexical_results, rrf_k=60):
        """Reciprocal Rank Fusion of two result lists."""
        scores: dict[str, float] = {}
        doc_map: dict[str, object] = {}
        for rank, doc in enumerate(semantic_results):
            key = doc.text[:200]
            scores[key] = scores.get(key, 0) + 1.0 / (rrf_k + rank + 1)
            doc_map[key] = doc
        for rank, doc in enumerate(lexical_results):
            key = doc.text[:200]
            scores[key] = scores.get(key, 0) + 1.0 / (rrf_k + rank + 1)
            if key not in doc_map:
                doc_map[key] = doc
        ranked_keys = sorted(scores, key=scores.get, reverse=True)
        return [doc_map[k] for k in ranked_keys]
    
    # ------ CORE METHODS ------------------------------------

    def connect(self):
        self._handler.connect(self._embedder, self._persist_directory)
        all_docs = self._handler.get_all_documents()
        self._build_bm25_index(all_docs)
        self._connected = True

    def get_all_document_for_user(self, access_context, user_id):
        if not isinstance(access_context, AccessContext):
            raise TypeError("access_context must be an AccessContext instance.")
        if access_context.role != "admin":
            raise PermissionError("Must be admin to access this resource")
        scoped_filter = access_context.apply_scope({"user_id": user_id})
        return self._handler.get_all_documents(filter=scoped_filter)

    def retrieve_documents(
        self,
        query,
        k=3,
        filter=None,
        rerank=True,
        candidates=10,
        access_context=None,
    ):
        self._ensure_connected()
        if not isinstance(access_context, AccessContext):
            raise TypeError("access_context must be an AccessContext instance.")
        scoped_filter = self._resolve_scope_filter(access_context, filter)
        fetch_k = max(candidates, k)

        # ── Step 1: Query doc_summaries ──────────────────────────────────
        summary_results = self._handler.search_summaries(
            query, k=10, filter=scoped_filter,
        )

        # ── Steps 2-4: Determine doc scope for chunk search ─────────────
        doc_ids = None

        if summary_results:
            scores = [score for _, score in summary_results]

            if len(scores) >= 2 and (scores[0] - scores[1]) < self._SCORE_GAP_THRESHOLD:
                doc_ids = None
            elif max(scores) < self._SUMMARY_SCORE_LOW:
                doc_ids = None
            else:
                filtered = [
                    (doc, score) for doc, score in summary_results
                    if score > self._SUMMARY_SCORE_HIGH
                ]
                if filtered:
                    doc_ids = [
                        doc.metadata.get("doc_id")
                        for doc, _ in filtered[:self._MAX_FILTERED_DOCS]
                    ]
                else:
                    doc_ids = [
                        doc.metadata.get("doc_id")
                        for doc, _ in summary_results[:self._MAX_FILTERED_DOCS]
                    ]

        # ── Step 5: Chunk retrieval (semantic + lexical) ────────────────
        semantic_results = self._handler.search(
            query, fetch_k, scoped_filter, doc_ids=doc_ids,
        )
        lexical_results = self._bm25_search(
            query, fetch_k, scoped_filter, doc_ids=doc_ids,
        )

        # ── Step 6: RRF fusion ──────────────────────────────────────────
        fused = self._rrf_fusion(semantic_results, lexical_results)

        # Optional cross-encoder reranking on top of RRF for extra quality
        if rerank and len(fused) > 1:
            if self._reranker is None:
                from sentence_transformers import CrossEncoder
                self._reranker = CrossEncoder(RERANKER_MODEL)
            rerank_pool = fused[:max(candidates, k * 2)]
            pairs = [(query, doc.text) for doc in rerank_pool]
            re_scores = self._reranker.predict(pairs)
            ranked = sorted(
                zip(re_scores, rerank_pool), key=lambda x: x[0], reverse=True,
            )
            return [doc for _, doc in ranked[:k]]

        return fused[:k]

    def upsert(self, summary_doc, chunk_docs, doc_id, access_context, reset=False):
        if reset and os.path.exists(self._persist_directory):
            shutil.rmtree(self._persist_directory)
        
        required_fields = ['user_id', 'tentant_id']
        for field in required_fields:
            if field not in doc.metadata:
                raise ValueError("Document doesn't have required fields!")

        if not isinstance(access_context, AccessContext):
            raise TypeError("access_context must be an AccessContext instance.")

        all_docs = ([summary_doc] if summary_doc else []) + (chunk_docs or [])

        if access_context.tenant_id:
            for doc in all_docs:
                if doc.metadata.get("tenant_id") != access_context.tenant_id:
                    raise PermissionError("Documents must match access_context tenant scope.")

        if not access_context.is_admin:
            for doc in all_docs:
                if doc.metadata.get("user_id") != access_context.user_id:
                    raise PermissionError("Users can only upsert their own documents.")

        self._handler.upsert(summary_doc, chunk_docs, doc_id, self._persist_directory)
        all_chunk_docs = self._handler.get_all_documents()
        self._build_bm25_index(all_chunk_docs)
        self._connected = True

    def delete_documents(self, access_context, filter):
        if not isinstance(access_context, AccessContext):
            raise TypeError("access_context must be an AccessContext instance.")
        scoped_filter = self._resolve_scope_filter(access_context, filter)

        # When using a remote Qdrant server there is no local persist_directory,
        # so the old os.path.exists guard would silently skip every delete.
        if not self._is_backend_reachable():
            return 0

        self._handler.connect(self._embedder, self._persist_directory)
        self._handler.delete(scoped_filter)
        all_docs = self._handler.get_all_documents()
        self._build_bm25_index(all_docs)
        self._connected = True
        return len(all_docs)

    def document_count(self, access_context, filter=None):
        self._ensure_connected()
        if not isinstance(access_context, AccessContext):
            raise TypeError("access_context must be an AccessContext instance.")
        scoped_filter = self._resolve_scope_filter(access_context, filter)
        return self._handler.count(scoped_filter)

    # ------ CLEAN UP METHODS ------------------------------------

    def close(self):
        self._handler.close()
        self._bm25 = None
        self._bm25_docs = []
        self._connected = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
