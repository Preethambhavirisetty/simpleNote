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
RERANKER_MODEL = _require_env("RERANKER_MODEL") # "cross-encoder/ms-marco-MiniLM-L-6-v2"
VECTOR_DB = _require_env("VECTOR_DB")
BREAKPOINT_PERCENTILE = int(_require_env("BREAKPOINT_PERCENTILE"))
QDRANT_COLLECTION = _require_env("QDRANT_COLLECTION")

LLM_API_BASE = _require_env("LLM_API_BASE")
LLM_API_KEY = _require_env("LLM_API_KEY")
LLM_MODEL = _require_env("LLM_MODEL")
LLM_CONTEXT_WINDOW = int(_require_env("LLM_CONTEXT_WINDOW"))
EMBEDDING_DEVICE = _require_env("EMBEDDING_DEVICE")

MESSAGE_BROKER_URL = _require_env("MESSAGE_BROKER_URL")
INGESTION_TASK_STRING=_require_env("INGESTION_TASK_STRING")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", MESSAGE_BROKER_URL)
INGESTION_QUEUE = os.getenv("INGESTION_QUEUE", "ingestion")

