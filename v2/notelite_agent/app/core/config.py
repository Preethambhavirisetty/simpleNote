import os

from dotenv import load_dotenv

from app.shared.utils import require_env


APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BASE_DIR = os.path.abspath(os.path.join(APP_DIR, ".."))

load_dotenv(os.path.join(BASE_DIR, ".env"))


# Paths
KNOWLEDGE_FOLDER_PATH = os.path.join(APP_DIR, "knowledge")
DB_PATH = os.path.join(APP_DIR, "db")


# Core application
SECRET_KEY = require_env("SECRET_KEY")
HF_TOKEN = require_env("HF_TOKEN")
BACKEND_API_URL = require_env("BACKEND_API_URL")

# Shared secret for agent HTTP endpoints. Set the same value in the backend's .env
# and send it as the `X-API-Key` header on every request to /ingest, /get-context, /retrieve.
AGENT_API_KEY = require_env("AGENT_API_KEY")


# Knowledge ingestion
SUPPORTED_EXTENSIONS = set(require_env("SUPPORTED_EXTENSIONS").split(","))
# Backward-compatible env name: this value is interpreted as tokens, not characters.
MAX_CHUNK_SIZE = int(require_env("MAX_CHUNK_SIZE"))
CHUNK_OVERLAP = int(require_env("CHUNK_OVERLAP"))
BREAKPOINT_PERCENTILE = int(require_env("BREAKPOINT_PERCENTILE"))


# Embeddings and retrieval
EMBEDDING_MODEL_BASE = require_env("EMBEDDING_MODEL_BASE", "").rstrip("/")
EMBEDDING_MODEL = require_env("EMBEDDING_MODEL")
EMBEDDING_API_KEY = require_env("EMBEDDING_API_KEY", "")
EMBEDDING_TIMEOUT = float(require_env("EMBEDDING_TIMEOUT", "120"))
EMBEDDING_DEVICE = require_env("EMBEDDING_DEVICE")
SPARSE_EMBEDDING_MODEL = require_env("SPARSE_EMBEDDING_MODEL")
RERANKER_MODEL = require_env("RERANKER_MODEL")

# Retrieval soft-scoring weights (should sum to 1.0)
SOFT_W_RRF = float(require_env("SOFT_W_RRF", "0.5"))
SOFT_W_KEYWORD = float(require_env("SOFT_W_KEYWORD", "0.15"))
SOFT_W_ENTITY = float(require_env("SOFT_W_ENTITY", "0.1"))
SOFT_W_QUALITY = float(require_env("SOFT_W_QUALITY", "0.15"))
SOFT_W_PARENT = float(require_env("SOFT_W_PARENT", "0.1"))


# Vector database
VECTOR_DB = require_env("VECTOR_DB")
QDRANT_URL = require_env("QDRANT_URL")
QDRANT_COLLECTION = require_env("QDRANT_COLLECTION")


# LLM
LLM_API_BASE = require_env("LLM_API_BASE")
CHAT_LLM_API_BASE = require_env("CHAT_LLM_API_BASE", LLM_API_BASE)
LLM_API_KEY = require_env("LLM_API_KEY")
LLM_MODEL = require_env("LLM_MODEL")
LLM_CONTEXT_WINDOW = int(require_env("LLM_CONTEXT_WINDOW"))
INTENT_LLM_MAX_TOKENS = int(require_env("INTENT_LLM_MAX_TOKENS", "128"))

# Path on the host (vLLM / OpenAI servers often use ``/v1/chat/completions``).
CHAT_COMPLETIONS_PATH = require_env("CHAT_COMPLETIONS_PATH", "/v1/chat/completions")
CHAT_STREAM_MODEL_LLAMA = require_env("CHAT_STREAM_MODEL_LLAMA", "llama3.1")
CHAT_STREAM_MODEL_MISTRAL = require_env("CHAT_STREAM_MODEL_MISTRAL", "mistral")

# ``runpod``: sync ``llm_call`` -> Mistral RunPod (primary to secondary);
# stream chat -> Llama RunPod only.
# ``legacy``: ``llm_call`` uses ``CHAT_LLM_API_BASE`` only (local dev).
# Streaming still uses RunPod Llama.
LLM_ENDPOINT_MODE = require_env("LLM_ENDPOINT_MODE", "runpod").strip().lower()


# RunPod - OpenAI-compatible chat (8001 = Mistral, 8002 = Llama on each host).
RUNPOD_MISTRAL = require_env(
    "RUNPOD_MISTRAL_SECONDARY",
    "https://bhsp25ijied2uu-8001.proxy.runpod.net",
)
RUNPOD_LLAMA = require_env(
    "RUNPOD_LLAMA",
    "https://den4sz9720zm6g-8002.proxy.runpod.net",
)


# Queues and workers
MESSAGE_BROKER_URL = require_env("MESSAGE_BROKER_URL")
CELERY_RESULT_BACKEND = require_env("CELERY_RESULT_BACKEND", MESSAGE_BROKER_URL)
INGESTION_TASK_STRING = require_env("INGESTION_TASK_STRING")
INGESTION_QUEUE = require_env("INGESTION_QUEUE", "ingestion")
CONVERSATION_QUEUE = require_env("CONVERSATION_QUEUE", "conversation")


# Database
# Used only for version guard checks - read-only, one query per upsert task.
# Accepts the same URL format as the backend (postgresql+psycopg://... is normalised automatically).
POSTGRES_DB_URL = require_env("POSTGRES_DB_URL")


# Observability
LOKI_URL = require_env("LOKI_URL")
