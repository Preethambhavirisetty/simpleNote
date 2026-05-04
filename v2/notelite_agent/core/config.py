import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

def _require_env(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return value


KNOWLEDGE_FOLDER_PATH = os.path.join(os.path.dirname(__file__), '..', 'knowledge')
DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'db')

SUPPORTED_EXTENSIONS = set(_require_env("SUPPORTED_EXTENSIONS").split(","))
MAX_CHUNK_SIZE = int(_require_env("MAX_CHUNK_SIZE"))
CHUNK_OVERLAP = int(_require_env("CHUNK_OVERLAP"))

EMBEDDING_MODEL = _require_env("EMBEDDING_MODEL") # "BAAI/bge-large-en-v1.5"
SPARSE_EMBEDDING_MODEL = _require_env("SPARSE_EMBEDDING_MODEL") # Qdrant/bm42-all-minilm-l6-v2-attentions
RERANKER_MODEL = _require_env("RERANKER_MODEL") # "cross-encoder/ms-marco-MiniLM-L-6-v2"
VECTOR_DB = _require_env("VECTOR_DB")
BREAKPOINT_PERCENTILE = int(_require_env("BREAKPOINT_PERCENTILE"))
QDRANT_COLLECTION = _require_env("QDRANT_COLLECTION")
QDRANT_URL = _require_env("QDRANT_URL")

LLM_API_BASE = _require_env("LLM_API_BASE")
LLM_API_KEY = _require_env("LLM_API_KEY")
LLM_MODEL = _require_env("LLM_MODEL")
LLM_CONTEXT_WINDOW = int(_require_env("LLM_CONTEXT_WINDOW"))
EMBEDDING_DEVICE = _require_env("EMBEDDING_DEVICE")

MESSAGE_BROKER_URL = _require_env("MESSAGE_BROKER_URL")
INGESTION_TASK_STRING = _require_env("INGESTION_TASK_STRING")

# Shared secret for agent HTTP endpoints.  Set the same value in the backend's .env
# and send it as the `X-API-Key` header on every request to /ingest, /get-context, /retrieve.
AGENT_API_KEY = _require_env("AGENT_API_KEY")
# Retrieval soft-scoring weights (should sum to 1.0)
SOFT_W_RRF = float(os.getenv("SOFT_W_RRF", "0.5"))
SOFT_W_KEYWORD = float(os.getenv("SOFT_W_KEYWORD", "0.15"))
SOFT_W_ENTITY = float(os.getenv("SOFT_W_ENTITY", "0.1"))
SOFT_W_QUALITY = float(os.getenv("SOFT_W_QUALITY", "0.15"))
SOFT_W_PARENT = float(os.getenv("SOFT_W_PARENT", "0.1"))

CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", MESSAGE_BROKER_URL)
INGESTION_QUEUE = os.getenv("INGESTION_QUEUE", "ingestion")
CONVERSATION_QUEUE = os.getenv("CONVERSATION_QUEUE", "conversation")

BACKEND_API_URL = _require_env("BACKEND_API_URL")

CHAT_LLM_API_BASE = os.getenv("CHAT_LLM_API_BASE", LLM_API_BASE)
INTENT_LLM_MAX_TOKENS = int(os.getenv("INTENT_LLM_MAX_TOKENS", "128"))

# RunPod — OpenAI-compatible chat (8001 = Mistral, 8002 = Llama on each host).
RUNPOD_MISTRAL_PRIMARY = os.getenv(
    "RUNPOD_MISTRAL_PRIMARY",
    "https://den4sz9720zm6g-8001.proxy.runpod.net",
)
RUNPOD_MISTRAL_SECONDARY = os.getenv(
    "RUNPOD_MISTRAL_SECONDARY",
    "https://bhsp25ijied2uu-8001.proxy.runpod.net",
)
RUNPOD_LLAMA_PRIMARY = os.getenv(
    "RUNPOD_LLAMA_PRIMARY",
    "https://den4sz9720zm6g-8002.proxy.runpod.net",
)
RUNPOD_LLAMA_SECONDARY = os.getenv(
    "RUNPOD_LLAMA_SECONDARY",
    "https://bhsp25ijied2uu-8002.proxy.runpod.net",
)
# Path on the host (vLLM / OpenAI servers often use ``/v1/chat/completions``).
CHAT_COMPLETIONS_PATH = os.getenv("CHAT_COMPLETIONS_PATH", "/v1/chat/completions")
CHAT_STREAM_MODEL_LLAMA = os.getenv("CHAT_STREAM_MODEL_LLAMA", "llama3.1")
CHAT_STREAM_MODEL_MISTRAL = os.getenv("CHAT_STREAM_MODEL_MISTRAL", "mistral")

# ``runpod``: sync ``llm_call`` → Mistral RunPod (primary→secondary); stream chat → Llama RunPod only.
# ``legacy``: ``llm_call`` uses ``CHAT_LLM_API_BASE`` only (local dev). Streaming still uses RunPod Llama.
LLM_ENDPOINT_MODE = os.getenv("LLM_ENDPOINT_MODE", "runpod").strip().lower()


def get_sync_llm_bases() -> list[str]:
    """Non-streaming ``llm_call`` targets — Mistral ports (8001), primary then fallback."""
    return [RUNPOD_MISTRAL_PRIMARY, RUNPOD_MISTRAL_SECONDARY]


def get_stream_chat_bases() -> list[str]:
    """Streaming chat only — Llama ports (8002), primary then fallback."""
    return [RUNPOD_LLAMA_PRIMARY, RUNPOD_LLAMA_SECONDARY]


def get_chat_completions_path() -> str:
    return CHAT_COMPLETIONS_PATH


def inference_completion_url(base: str) -> str:
    """Full chat-completions URL for a RunPod/OpenAI host root (no trailing path)."""
    b = base.rstrip("/")
    path = CHAT_COMPLETIONS_PATH.strip()
    if not path.startswith("/"):
        path = "/" + path
    return f"{b}{path}"


def get_sync_llm_model_name() -> str:
    """Default model id for Mistral (non-stream) when callers omit ``model`` in payload."""
    return CHAT_STREAM_MODEL_MISTRAL


def get_llama_stream_model_name() -> str:
    """Model id for streaming chat on Llama RunPod."""
    return CHAT_STREAM_MODEL_LLAMA

# Used only for version guard checks — read-only, one query per upsert task.
# Accepts the same URL format as the backend (postgresql+psycopg://... is normalised automatically).
POSTGRES_DB_URL = _require_env("POSTGRES_DB_URL")

