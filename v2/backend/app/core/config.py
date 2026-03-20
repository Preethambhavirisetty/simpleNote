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
