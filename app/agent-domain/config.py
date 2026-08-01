import os

def require_env(key: str, default:str=None) -> str:
    value = os.getenv(key, default)
    if value is None:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return value


EMBEDDING_MODEL = require_env("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
EMBEDDING_DEVICE = require_env("EMBEDDING_DEVICE", "cpu")
PLAYBOOK_SEARCH_LIMIT = int(require_env("PLAYBOOK_SEARCH_LIMIT", "5"))

# How many playbooks the selector LLM is willing to read at once. At or below
# this count every playbook is a candidate and semantic search is skipped
# entirely; above it, search narrows the catalog to this many.
PLAYBOOK_CANDIDATE_LIMIT = int(require_env("PLAYBOOK_CANDIDATE_LIMIT", "7"))
