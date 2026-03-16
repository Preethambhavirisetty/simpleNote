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
MONGO_DB_URL = _require_env("MONGO_DB_URL")
COLLECTION_NAME = _require_env("COLLECTION_NAME")
POSTGRES_DB_URL = os.getenv("POSTGRES_DB_URL")