"""Vector store facade — retrieval, upsert, and scoring.

Orchestrates two-stage retrieval:
    1. Summary collection (dense + questions vectors) → doc_id scoping
    2. Chunk collection (hybrid dense + sparse RRF)
    3. Soft scoring (keyword/entity Jaccard + quality)
    4. Optional cross-encoder reranking
"""

import os
import shutil
import sys
import time
import importlib

import structlog

from core.config import (
    DB_PATH, VECTOR_DB, RERANKER_MODEL, QDRANT_URL,
    SOFT_W_RRF, SOFT_W_KEYWORD, SOFT_W_ENTITY, SOFT_W_QUALITY, SOFT_W_PARENT,
)
from pipeline.keywords import extract_keywords
from core.contracts import AccessContext
from core.settings import is_llama_index_settings_initialized
from llama_index.core import Settings

log = structlog.get_logger()


_SUMMARY_SCORE_HIGH = 0.8
_SUMMARY_SCORE_LOW = 0.7
_SCORE_GAP_THRESHOLD = 0.05
_MAX_FILTERED_DOCS = 3

_QUERY_STOP = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been",
    "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "can", "shall",
    "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "as", "about", "what", "which", "who", "where", "when", "why", "how",
    "not", "no", "but", "or", "and", "if", "so", "then",
    "my", "your", "his", "her", "its", "our", "their",
    "i", "you", "he", "she", "it", "we", "they",
    "this", "that", "these", "those", "me", "him", "us", "them",
})


# ── Soft scoring helpers ─────────────────────────────────────────────────

def _tokenize_phrases(phrases):
    """Break keyword/entity phrases into lowercased tokens, expanding hyphens."""
    tokens = set()
    for p in phrases:
        for w in p.lower().split():
            tokens.add(w)
            if '-' in w:
                tokens.update(part for part in w.split('-') if part)
    return {t for t in tokens if len(t) > 1}


def _jaccard(set_a, set_b):
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def _entity_recall(query_ent_set, doc_ent_set):
    """Fraction of query entities found in the doc (recall-based)."""
    if not query_ent_set:
        return 0.0
    return len(query_ent_set & doc_ent_set) / len(query_ent_set)


def _soft_score(query, results):
    """Re-sort (doc, rrf_score) pairs by blending RRF, keyword/entity
    similarity, parent-summary overlap, and stored doc_quality.
    """
    if len(results) < 2:
        return results

    try:
        query_kws, query_ents = extract_keywords(query, top_n=10)
    except Exception:
        query_kws, query_ents = [], []

    if query_kws:
        query_kw_tokens = _tokenize_phrases(query_kws)
    else:
        query_kw_tokens = {
            w.lower() for w in query.split()
            if w.lower() not in _QUERY_STOP and len(w) > 1
        }
    query_ent_set = {e.lower() for e in query_ents}

    rrf_scores = [s for _, s in results]
    min_s, max_s = min(rrf_scores), max(rrf_scores)
    spread = max_s - min_s if max_s > min_s else 1.0

    scored = []
    for doc, rrf_raw in results:
        rrf_norm = (rrf_raw - min_s) / spread

        doc_kw_tokens = _tokenize_phrases(doc.metadata.get("keywords", []))
        doc_ent_set = {e.lower() for e in doc.metadata.get("entities", [])}

        kw_sim = _jaccard(query_kw_tokens, doc_kw_tokens)
        ent_sim = _entity_recall(query_ent_set, doc_ent_set)

        parent_text = doc.metadata.get("parent_summary", "")
        if parent_text:
            parent_tokens = {
                w.lower() for w in parent_text.split()
                if w.lower() not in _QUERY_STOP and len(w) > 1
            }
            parent_sim = _jaccard(query_kw_tokens, parent_tokens)
        else:
            parent_sim = 0.0

        quality = doc.metadata.get("doc_quality", 0.0)

        soft = (
            SOFT_W_RRF * rrf_norm
            + SOFT_W_KEYWORD * kw_sim
            + SOFT_W_ENTITY * ent_sim
            + SOFT_W_PARENT * parent_sim
            + SOFT_W_QUALITY * quality
        )
        soft += rrf_raw * 1e-6

        scored.append((doc, soft))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


# ── Reranker singleton ────────────────────────────────────────────────────

_reranker_instance = None

def _get_reranker():
    global _reranker_instance
    if _reranker_instance is None:
        from sentence_transformers import CrossEncoder
        _reranker_instance = CrossEncoder(RERANKER_MODEL)
        log.info("reranker.loaded", model=RERANKER_MODEL)
    return _reranker_instance


# ── VectorStore ──────────────────────────────────────────────────────────

class VectorStore:
    def __init__(self, persist_directory=DB_PATH):
        self._persist_directory = persist_directory
        if not is_llama_index_settings_initialized():
            raise RuntimeError(
                "LlamaIndex settings are not initialized. "
                "Call init_llama_index_settings() once at application startup."
            )
        self._embedder = Settings.embed_model
        self._handler = self._load_handler(VECTOR_DB)
        self._connected = False

    @property
    def embedder(self):
        return self._embedder

    @staticmethod
    def _load_handler(vector_db_name):
        """Load handler factory robustly across runtime contexts."""
        module_candidates = ["handlers", "rag.handlers"]
        for module_name in module_candidates:
            try:
                module = importlib.import_module(module_name)
                return module.get_handler(vector_db_name)
            except ModuleNotFoundError:
                continue

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
        return bool(QDRANT_URL) or os.path.exists(self._persist_directory)

    def _ensure_connected(self):
        if not self._connected:
            if self._is_backend_reachable():
                self.connect()
            else:
                raise RuntimeError("No vector store found. Call load() to ingest documents first.")

    def connect(self):
        self._handler.connect(self._embedder, self._persist_directory)
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
        """Two-stage retrieval: summaries → doc scoping → hybrid chunk search → soft score → rerank."""
        self._ensure_connected()
        if not isinstance(access_context, AccessContext):
            raise TypeError("access_context must be an AccessContext instance.")
        scoped_filter = self._resolve_scope_filter(access_context, filter)
        fetch_k = max(candidates, k)

        # ── Summary search ───────────────────────────────────────────────
        t0 = time.monotonic()
        summary_results = self._handler.search_summaries(query, k=10, filter=scoped_filter)

        doc_ids = None
        if summary_results:
            scores = [score for _, score in summary_results]

            if len(scores) >= 2 and (scores[0] - scores[1]) < _SCORE_GAP_THRESHOLD:
                doc_ids = None
            elif max(scores) < _SUMMARY_SCORE_LOW:
                doc_ids = None
            else:
                filtered = [
                    (doc, score) for doc, score in summary_results
                    if score > _SUMMARY_SCORE_HIGH
                ]
                if filtered:
                    doc_ids = [
                        doc.metadata.get("doc_id")
                        for doc, _ in filtered[:_MAX_FILTERED_DOCS]
                    ]
                else:
                    doc_ids = [
                        doc.metadata.get("doc_id")
                        for doc, _ in summary_results[:_MAX_FILTERED_DOCS]
                    ]

        summary_ms = int((time.monotonic() - t0) * 1000)
        log.info(
            "retrieval.summary_search",
            result_count=len(summary_results),
            top_scores=[round(s, 4) for _, s in summary_results[:5]],
            doc_ids_scoped=doc_ids,
            latency_ms=summary_ms,
        )

        # ── Chunk search ─────────────────────────────────────────────────
        t1 = time.monotonic()
        results = self._handler.search(query, fetch_k, scoped_filter, doc_ids=doc_ids)
        chunk_ms = int((time.monotonic() - t1) * 1000)
        log.info(
            "retrieval.chunk_search",
            candidate_count=len(results),
            latency_ms=chunk_ms,
        )

        # ── Soft scoring ─────────────────────────────────────────────────
        t2 = time.monotonic()
        results = _soft_score(query, results)
        soft_ms = int((time.monotonic() - t2) * 1000)
        log.info("retrieval.soft_score", latency_ms=soft_ms)

        # ── Reranking ────────────────────────────────────────────────────
        if rerank and len(results) > 1:
            t3 = time.monotonic()
            reranker = _get_reranker()
            rerank_pool = [doc for doc, _ in results[:max(candidates, k * 2)]]
            pairs = [(query, doc.text) for doc in rerank_pool]
            re_scores = reranker.predict(pairs)
            ranked = sorted(
                zip(re_scores, rerank_pool), key=lambda x: x[0], reverse=True,
            )
            rerank_ms = int((time.monotonic() - t3) * 1000)
            log.info(
                "retrieval.rerank",
                input_count=len(rerank_pool),
                output_count=k,
                latency_ms=rerank_ms,
            )
            return [doc for _, doc in ranked[:k]]

        return [doc for doc, _ in results[:k]]

    def upsert(self, summary_doc, chunk_docs, doc_id, access_context, reset=False):
        if reset and os.path.exists(self._persist_directory):
            shutil.rmtree(self._persist_directory)

        if not isinstance(access_context, AccessContext):
            raise TypeError("access_context must be an AccessContext instance.")

        all_docs = ([summary_doc] if summary_doc else []) + (chunk_docs or [])

        required_fields = ['user_id', 'tenant_id']
        for doc in all_docs:
            for field in required_fields:
                if field not in doc.metadata:
                    raise ValueError(f"Document missing required field: {field}")

        if access_context.tenant_id:
            for doc in all_docs:
                if doc.metadata.get("tenant_id") != access_context.tenant_id:
                    raise PermissionError("Documents must match access_context tenant scope.")

        if not access_context.is_admin:
            for doc in all_docs:
                if doc.metadata.get("user_id") != access_context.user_id:
                    raise PermissionError("Users can only upsert their own documents.")

        self._handler.upsert(summary_doc, chunk_docs, doc_id, self._persist_directory)
        self._connected = True

    def delete_documents(self, access_context, filter):
        if not isinstance(access_context, AccessContext):
            raise TypeError("access_context must be an AccessContext instance.")
        scoped_filter = self._resolve_scope_filter(access_context, filter)

        if not self._is_backend_reachable():
            return 0

        self._handler.connect(self._embedder, self._persist_directory)
        self._handler.delete(scoped_filter)
        self._connected = True
        return self._handler.count()

    def document_count(self, access_context, filter=None):
        self._ensure_connected()
        if not isinstance(access_context, AccessContext):
            raise TypeError("access_context must be an AccessContext instance.")
        scoped_filter = self._resolve_scope_filter(access_context, filter)
        return self._handler.count(scoped_filter)

    def scroll_all_chunks(self, access_context: AccessContext):
        """Return every chunk document for the scoped user/tenant (text + metadata)."""
        self._ensure_connected()
        if not isinstance(access_context, AccessContext):
            raise TypeError("access_context must be an AccessContext instance.")
        scoped_filter = self._resolve_scope_filter(access_context)
        return self._handler.scroll_chunks(filter=scoped_filter)

    def close(self):
        self._handler.close()
        self._connected = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
