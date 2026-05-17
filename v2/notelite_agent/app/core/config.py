import os

from dotenv import load_dotenv

from app.shared.utils import require_env


APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BASE_DIR = os.path.abspath(os.path.join(APP_DIR, ".."))

load_dotenv(os.path.join(BASE_DIR, ".env"))


# Core application
SECRET_KEY = require_env("SECRET_KEY")
BACKEND_API_URL = require_env("BACKEND_API_URL")
# Shared secret for agent HTTP endpoints. Set the same value in the backend's .env
# and send it as the X-API-Key header on every ingest/retrieve request.
AGENT_API_KEY = require_env("AGENT_API_KEY", "")


# Knowledge ingestion
MAX_CHUNK_SIZE = int(require_env("MAX_CHUNK_SIZE"))
CHUNK_OVERLAP = int(require_env("CHUNK_OVERLAP"))
BREAKPOINT_PERCENTILE = int(require_env("BREAKPOINT_PERCENTILE"))


# Embeddings — always served remotely from RunPod (no local GPU on EC2)
EMBEDDING_MODEL_BASE = require_env("EMBEDDING_MODEL_BASE", "").rstrip("/")
EMBEDDING_MODEL = require_env("EMBEDDING_MODEL")
EMBEDDING_API_KEY = require_env("EMBEDDING_API_KEY", "")
EMBEDDING_TIMEOUT = float(require_env("EMBEDDING_TIMEOUT", "120"))


# Vector database
QDRANT_URL = require_env("QDRANT_URL")
QDRANT_COLLECTION = require_env("QDRANT_COLLECTION")


# LLM — served remotely from RunPod
LLM_API_BASE = require_env("LLM_API_BASE")
LLM_API_KEY = require_env("LLM_API_KEY")
LLM_MODEL = require_env("LLM_MODEL")
LLM_CONTEXT_WINDOW = int(require_env("LLM_CONTEXT_WINDOW"))


# Queues and workers
MESSAGE_BROKER_URL = require_env("MESSAGE_BROKER_URL")
CELERY_RESULT_BACKEND = require_env("CELERY_RESULT_BACKEND", MESSAGE_BROKER_URL)
INGESTION_TASK_STRING = require_env("INGESTION_TASK_STRING")
INGESTION_QUEUE = require_env("INGESTION_QUEUE", "ingestion")
CONVERSATION_QUEUE = require_env("CONVERSATION_QUEUE", "conversation")


# Database — read-only version guard checks, one query per upsert task
POSTGRES_DB_URL = require_env("POSTGRES_DB_URL")
