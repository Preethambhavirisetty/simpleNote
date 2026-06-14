import os

from dotenv import load_dotenv

load_dotenv()


def _require_env(name: str, default:str=None) -> str:
    value = os.getenv(name, default)
    if value is None:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


SECRET_KEY = _require_env("SECRET_KEY")
HASH_ALGORITHM = _require_env("HASH_ALGORITHM", "HS256")
POSTGRES_DB_URL = _require_env("POSTGRES_DB_URL")
MESSAGE_BROKER_URL = _require_env("MESSAGE_BROKER_URL")
CELERY_RESULT_BACKEND = _require_env("CELERY_RESULT_BACKEND")
INGESTION_TASK_STRING = _require_env("INGESTION_TASK_STRING")
INGESTION_QUEUE = _require_env("INGESTION_QUEUE", "ingestion")

# Shared secret for service-to-service calls from the notelite_agent.
AGENT_API_KEY = _require_env("AGENT_API_KEY")

# Internal task: compute note_size and persist it — handled by the backend's own Celery worker
NOTE_SIZE_TASK_STRING = _require_env("NOTE_SIZE_TASK_STRING", "notelite.tasks.notes.compute_note_size")
NOTE_SIZE_QUEUE = _require_env("NOTE_SIZE_QUEUE", "note_size")
