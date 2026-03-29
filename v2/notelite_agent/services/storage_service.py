import os
import shutil
import sys
import importlib
from core.config import (
    DB_PATH, VECTOR_DB, RERANKER_MODEL, QDRANT_URL,
    SOFT_W_RRF, SOFT_W_KEYWORD, SOFT_W_ENTITY, SOFT_W_QUALITY, SOFT_W_PARENT,
)
from handlers.keyword_extractor import extract_keywords
from core.contracts import AccessContext
from core.settings import is_llama_index_settings_initialized
from llama_index.core import Settings


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

    Uses extract_keywords for POS-validated query analysis with a
    stopword-filtered fallback when extraction returns nothing.
    """
    if len(results) < 2:
        return results

    # ── Query analysis via the full keyword/entity pipeline ───────
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

    # ── RRF normalisation (min-max to [0, 1]) ────────────────────
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

        # Tiebreaker: preserve original RRF ordering for equal soft scores
        soft += rrf_raw * 1e-6

        scored.append((doc, soft))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


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

    def _ensure_connected(self):
        if not self._connected:
            if self._is_backend_reachable():
                self.connect()
            else:
                raise RuntimeError("No vector store found. Call load() to ingest documents first.")

    # ------ CORE METHODS ------------------------------------

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
        """
        Query
        → Step 1: Summary collection (dense search) → doc_id scoping
        → Step 2: Chunk collection (hybrid: dense + sparse RRF)
        → Step 3.5: Soft scoring (new)
        → Step 4: Cross-encoder rerank
        → Top-k results
        """
        self._ensure_connected()
        if not isinstance(access_context, AccessContext):
            raise TypeError("access_context must be an AccessContext instance.")
        scoped_filter = self._resolve_scope_filter(access_context, filter)
        fetch_k = max(candidates, k)

        # ── Step 1: Query doc_summaries (dense) ──────────────────────────
        summary_results = self._handler.search_summaries(
            query, k=10, filter=scoped_filter,
        )

        # ── Step 2: Determine doc scope for chunk search ─────────────────
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

        # ── Step 3: Hybrid chunk retrieval (dense + sparse in Qdrant) ────
        results = self._handler.search(
            query, fetch_k, scoped_filter, doc_ids=doc_ids,
        )

        # ── Step 3.5: Soft scoring (RRF + keyword/entity Jaccard + quality)
        results = _soft_score(query, results)

        # ── Step 4: Optional cross-encoder reranking ─────────────────────
        if rerank and len(results) > 1:
            if self._reranker is None:
                from sentence_transformers import CrossEncoder
                self._reranker = CrossEncoder(RERANKER_MODEL)
            rerank_pool = [doc for doc, _ in results[:max(candidates, k * 2)]]
            pairs = [(query, doc.text) for doc in rerank_pool]
            re_scores = self._reranker.predict(pairs)
            ranked = sorted(
                zip(re_scores, rerank_pool), key=lambda x: x[0], reverse=True,
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
        
        print("***************** qdrant upset invoked! *****************")
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

    # ------ CLEAN UP METHODS ------------------------------------

    def close(self):
        self._handler.close()
        self._connected = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()



if __name__ == "__main__":
    text = """
The document/documents begins with the idea that the organization is always doing something, even when it is not doing very much at all. On paper, the system appears organized, but in practice the system is mostly a collection of activities, operations, processes, notes, reports, and discussions that are repeated in different forms throughout the day. During the day, the team talks about coordination, and at night the same team talks about coordination again, but with slightly different words, as if repetition itself were a strategy. The report about the work refers to the report as if the report were both the cause and the effect of the work.

In the first section, there is a mention of alignment, strategy, management, implementation, workflow, integration, and output. In the second section, those same terms appear again, but they are surrounded by words like thing, stuff, part, item, element, factor, aspect, and piece. The text keeps saying that one thing leads to another thing, that one activity influences another activity, and that one operation affects another operation, yet the exact relationship between these things is never fully explained. The result is a situation where the situation itself becomes the subject of the discussion.

The project team is described in several ways. Sometimes it is the operations team. Sometimes it is the management team. Sometimes it is the delivery team. Sometimes it is simply the team. Sometimes it is not even a team but a group, a unit, a collection, or a set of people working on the same thing. The document also refers to the organization, the company, the department, the office, and the group as though these were interchangeable, which makes entity extraction difficult. The organization wants better organization, the company wants better coordination, and the department wants better management, but all of these goals are expressed using the same generic language.

There are multiple references to the phase, the stage, the step, the process, the procedure, the cycle, and the sequence. Every phase contains a review, every review contains a note, every note contains a comment, every comment contains a remark, and every remark contains another reference to the same project. The implementation phase is mentioned alongside the planning phase, the analysis phase, the execution phase, the validation phase, and the closing phase, but each one seems to contain the same content repeated under a different heading. The document makes it look like there are many distinct stages when in reality there is very little variation.

The text also includes a long discussion of data, logs, records, outputs, results, metrics, values, and summaries. The data is said to support the report, but the report is also said to define the data. The logs are said to show the output, but the output is also said to confirm the logs. The metrics are said to measure performance, but performance is never clearly separated from activity, work, or output. This creates a loop in which every noun points back to another noun, and every conclusion points back to the original statement.

Sometimes the document switches to more abstract language. It talks about improvement, optimization, efficiency, quality, consistency, reliability, structure, clarity, and stability. These are repeated in different combinations, often with modifiers like better, more, less, stronger, clearer, faster, and simpler. The text claims that the workflow should be clearer, the operations should be smoother, the coordination should be stronger, the management should be better, and the integration should be tighter, but these claims are not backed by concrete detail. Instead, the document uses phrases like “the thing we need,” “the way forward,” “the right approach,” and “the better path,” which sound useful but do not add much semantic precision.

At several points, the document becomes circular. It says that the report should improve the report. It says that the summary should summarize the summary. It says that the review should review the review. It says that the process should process the process. It says that the system should stabilize the system. These statements are grammatically valid but semantically weak. They create a worst-case scenario for a keyword extractor because the same words appear in many contexts, often without clear importance or hierarchy.

The final section repeats the core themes one more time: team, report, work, process, system, output, management, operations, coordination, integration, workflow, phase, data, log, result, organization, and situation. The conclusion does not introduce new information; it only rephrases what has already been said. If a keyword extractor relies too heavily on frequency, it may surface the wrong terms. If it relies too heavily on shallow phrase matching, it may keep phrases that are merely repeated rather than truly meaningful. If it relies too heavily on surface form without normalization, it may treat plural and singular variants as unrelated terms even though they refer to the same concept.

In that sense, the document is designed to be difficult. It is long enough to create many candidate spans, repetitive enough to inflate common terms, abstract enough to blur semantic boundaries, and vague enough to make subphrase pruning uncertain. It includes multiple references to day and night, to the same idea expressed in different ways, to overlapping concepts like management and coordination, and to generic nouns like thing, stuff, part, piece, item, and element. A keyword extractor has to decide what matters most, even though the text keeps suggesting that almost everything matters equally. That is exactly what makes it a useful stress test.
"""
    import time
    start = time.time()
    data = {
        "text": text,
        "user_id": "SAMPLEUSER01",
        "folder_id": "SAMPLESFOLDER01",
        "note_id": "SAMPLENOTE01",
        "role": "user",
        "tenant_id": "TENANT01",
        "folder_title": "SAMPLE FOLDER TITLE1",
        "note_title": "SAMPLE NOTE TITLE1",
        "description": "SAMPLE DESCRIPTION 1",
        "tags": [
            "tag1",
            "tag2"
        ]
    }

    doc_id, summary_doc, chunk_docs = get_document_objects(data)
    print(doc_id, summary_doc, '\n', chunk_docs[0], time.time() - start)