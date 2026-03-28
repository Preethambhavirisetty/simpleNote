import os
import shutil
import sys
import importlib
from rank_bm25 import BM25Okapi
from core.config import DB_PATH, VECTOR_DB, RERANKER_MODEL, QDRANT_URL
from core.contracts import AccessContext
from core.settings import is_llama_index_settings_initialized
from llama_index.core import Settings


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

    def connect(self):
        self._handler.connect(self._embedder, self._persist_directory)
        all_docs = self._handler.get_all_documents()
        self._build_bm25_index(all_docs)
        self._connected = True

    def upsert(self, documents, doc_id, access_context, reset=False):
        if reset and os.path.exists(self._persist_directory):
            shutil.rmtree(self._persist_directory)

        if not isinstance(access_context, AccessContext):
            raise TypeError("access_context must be an AccessContext instance.")

        # Tenant scoping is always enforced when tenant context is provided.
        if access_context.tenant_id:
            for doc in documents:
                if doc.metadata.get("tenant_id") != access_context.tenant_id:
                    raise PermissionError("Documents must match access_context tenant scope.")

        if not access_context.is_admin:
            for doc in documents:
                if doc.metadata.get("user_id") != access_context.user_id:
                    raise PermissionError("Users can only upsert their own documents.")

        self._handler.upsert(documents, doc_id, self._persist_directory)
        all_docs = self._handler.get_all_documents()
        self._build_bm25_index(all_docs)
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

    def _ensure_connected(self):
        if not self._connected:
            if self._is_backend_reachable():
                self.connect()
            else:
                raise RuntimeError("No vector store found. Call load() to ingest documents first.")

    def _bm25_search(self, query, k, filter=None):
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

        top = sorted(indices, key=lambda i: scores[i], reverse=True)[:k]
        return [self._bm25_docs[i] for i in top if scores[i] > 0]
    
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
        dense_results = self._handler.search(query, fetch_k, scoped_filter)
        sparse_results = self._bm25_search(query, fetch_k, scoped_filter)

        seen = set()
        merged = []
        for doc in dense_results + sparse_results:
            key = doc.text[:200]
            if key not in seen:
                seen.add(key)
                merged.append(doc)

        if rerank and len(merged) > 1:
            if self._reranker is None:
                from sentence_transformers import CrossEncoder
                self._reranker = CrossEncoder(RERANKER_MODEL)
            pairs = [(query, doc.text) for doc in merged]
            scores = self._reranker.predict(pairs)
            ranked = sorted(zip(scores, merged), key=lambda x: x[0], reverse=True)
            return [doc for _, doc in ranked[:k]]

        return merged[:k]

    def document_count(self, access_context, filter=None):
        self._ensure_connected()
        if not isinstance(access_context, AccessContext):
            raise TypeError("access_context must be an AccessContext instance.")
        scoped_filter = self._resolve_scope_filter(access_context, filter)
        return self._handler.count(scoped_filter)

    def close(self):
        self._handler.close()
        self._bm25 = None
        self._bm25_docs = []
        self._connected = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
