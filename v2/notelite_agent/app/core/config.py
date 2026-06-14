import os

from dotenv import load_dotenv

from app.shared.utils import require_env


APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BASE_DIR = os.path.abspath(os.path.join(APP_DIR, ".."))

load_dotenv(os.path.join(BASE_DIR, ".env"))


# Core application
SECRET_KEY = require_env("SECRET_KEY")
BACKEND_INTERNAL_URL_BASE = require_env("BACKEND_INTERNAL_URL_BASE")
AGENT_API_KEY = require_env("AGENT_API_KEY")


# Prompt selection
ACTIVE_CHAT_SYSTEM_VERSION = require_env("ACTIVE_CHAT_SYSTEM_VERSION")
ACTIVE_SUMMARIZER_VERSION = require_env("ACTIVE_SUMMARIZER_VERSION")


# Knowledge ingestion
MAX_CHUNK_SIZE = int(require_env("MAX_CHUNK_SIZE"))
CHUNK_OVERLAP = int(require_env("CHUNK_OVERLAP"))
BREAKPOINT_PERCENTILE = int(require_env("BREAKPOINT_PERCENTILE"))
KEYWORD_MIN_CHUNK_TOKENS = int(require_env("KEYWORD_MIN_CHUNK_TOKENS", "5"))
KEYWORD_EXTRACTION_MAX_CHUNKS = int(require_env("KEYWORD_EXTRACTION_MAX_CHUNKS", "10"))
KEYWORD_EXTRACTION_MAX_TOKENS = int(require_env("KEYWORD_EXTRACTION_MAX_TOKENS", "3000"))
KEYWORD_EXTRACTION_CONCURRENCY = int(require_env("KEYWORD_EXTRACTION_CONCURRENCY", "1"))
INDEX_CODE_CHUNKS = require_env("INDEX_CODE_CHUNKS", "false").lower() == "true"
INDEX_JSON_CHUNKS = require_env("INDEX_JSON_CHUNKS", "false").lower() == "true"
MIN_INDEXABLE_TOKENS = int(require_env("MIN_INDEXABLE_TOKENS", "10"))
MIN_SUMMARY_CHUNK_TOKENS = int(require_env("MIN_SUMMARY_CHUNK_TOKENS", "10"))


# Embeddings — always served remotely from RunPod (no local GPU on EC2)
EMBEDDING_MODEL_BASE = require_env("EMBEDDING_MODEL_BASE", "").rstrip("/")
EMBEDDING_MODEL = require_env("EMBEDDING_MODEL")
EMBEDDING_API_KEY = require_env("EMBEDDING_API_KEY", "")
EMBEDDING_TIMEOUT = float(require_env("EMBEDDING_TIMEOUT", "120"))
SEMANTIC_CHUNKING_TIMEOUT = float(require_env("SEMANTIC_CHUNKING_TIMEOUT", "8"))
SEMANTIC_CHUNKING_FAILURE_COOLDOWN = float(require_env("SEMANTIC_CHUNKING_FAILURE_COOLDOWN", "60"))


# Vector database
QDRANT_URL = require_env("QDRANT_URL")
QDRANT_COLLECTION = require_env("QDRANT_COLLECTION")


# LLM — served remotely from RunPod
LLM_API_BASE = require_env("LLM_API_BASE")
LLM_API_KEY = require_env("LLM_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL")  # Legacy fallback for existing deployments.
LLM_REASONER_MODEL = require_env("LLM_REASONER_MODEL", LLM_MODEL)
LLM_SUMMARIZER_MODEL = require_env("LLM_SUMMARIZER_MODEL", LLM_MODEL)
LLM_CONTEXT_WINDOW = int(require_env("LLM_CONTEXT_WINDOW"))

# Summarization budgets
DIRECT_SUMMARY_THRESHOLD = int(require_env("DIRECT_SUMMARY_THRESHOLD", "3000"))
SUMMARY_GROUP_TOKEN_LIMIT = min(
    int(require_env("SUMMARY_GROUP_TOKEN_LIMIT", str(int(LLM_CONTEXT_WINDOW * 0.75)))),
    LLM_CONTEXT_WINDOW,
)
SUMMARY_GROUP_TOKEN_BUFFER = int(require_env("SUMMARY_GROUP_TOKEN_BUFFER", "128"))
GROUP_SUMMARY_MAX_TOKENS = int(require_env("GROUP_SUMMARY_MAX_TOKENS", "150"))
FINAL_SUMMARY_MAX_TOKENS = int(require_env("FINAL_SUMMARY_MAX_TOKENS", "384"))
FALLBACK_SUMMARY_CHAR_CAP = int(require_env("FALLBACK_SUMMARY_CHAR_CAP", "1400"))


# Queues and workers
MESSAGE_BROKER_URL = require_env("MESSAGE_BROKER_URL")
CELERY_RESULT_BACKEND = require_env("CELERY_RESULT_BACKEND", MESSAGE_BROKER_URL)
INGESTION_TASK_STRING = require_env("INGESTION_TASK_STRING")
INGESTION_QUEUE = require_env("INGESTION_QUEUE", "ingestion")
CONVERSATION_QUEUE = require_env("CONVERSATION_QUEUE", "conversation")


# Database — read-only version guard checks, one query per upsert task
POSTGRES_DB_URL = require_env("POSTGRES_DB_URL")


# Reranker — optional remote cross-encoder (Cohere-compatible API).
# Leave empty to skip reranking and rely on RRF scores from Qdrant.
RERANKER_API_BASE = os.getenv("RERANKER_API_BASE", "").rstrip("/")
RERANKER_API_KEY = os.getenv("RERANKER_API_KEY", "")
RERANKER_MIN_RELEVANCE_SCORE = float(
    require_env("RERANKER_MIN_RELEVANCE_SCORE", "0.0")
)

# Retrieval pipeline
HYDE_TIMEOUT = float(require_env("HYDE_TIMEOUT", "2"))
HYDE_MAX_TOKENS = int(require_env("HYDE_MAX_TOKENS", "150"))
RETRIEVAL_SEARCH_WORKERS = int(require_env("RETRIEVAL_SEARCH_WORKERS", "5"))
RETRIEVAL_RRF_K = int(require_env("RETRIEVAL_RRF_K", "60"))
RETRIEVAL_RRF_TOP_K = int(require_env("RETRIEVAL_RRF_TOP_K", "30"))
RETRIEVAL_CHUNK_BUDGET = int(require_env("RETRIEVAL_CHUNK_BUDGET", "2000"))
RETRIEVAL_SUMMARY_BUDGET = int(require_env("RETRIEVAL_SUMMARY_BUDGET", "600"))
RETRIEVAL_HISTORY_BUDGET = int(require_env("RETRIEVAL_HISTORY_BUDGET", "400"))
RETRIEVAL_MAX_SUMMARIES = int(require_env("RETRIEVAL_MAX_SUMMARIES", "2"))
RETRIEVAL_RRF_WEIGHTS = {
    "chunk_dense_original": float(require_env("RRF_WEIGHT_CHUNK_DENSE_ORIGINAL", "1.0")),
    "chunk_dense_hyde": float(require_env("RRF_WEIGHT_CHUNK_DENSE_HYDE", "0.8")),
    "chunk_sparse_bm25": float(require_env("RRF_WEIGHT_CHUNK_SPARSE_BM25", "0.9")),
    "chunk_filtered_dense": float(require_env("RRF_WEIGHT_CHUNK_FILTERED_DENSE", "0.7")),
    "chunk_filtered_sparse": float(require_env("RRF_WEIGHT_CHUNK_FILTERED_SPARSE", "0.6")),
}
