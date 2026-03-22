import os

from dotenv import load_dotenv

load_dotenv()


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


SECRET_KEY = _require_env("SECRET_KEY")
HASH_ALGORITHM = os.getenv("HASH_ALGORITHM", "HS256")
POSTGRES_DB_URL = _require_env("POSTGRES_DB_URL")
MESSAGE_BROKER_URL = _require_env("MESSAGE_BROKER_URL")
CELERY_RESULT_BACKEND = _require_env("CELERY_RESULT_BACKEND")
INGESTION_TASK_STRING=_require_env("INGESTION_TASK_STRING")
INGESTION_QUEUE = os.getenv("INGESTION_QUEUE", "ingestion")
