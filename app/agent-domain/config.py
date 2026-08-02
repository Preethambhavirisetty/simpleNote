import os

from dotenv import load_dotenv


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Real environment variables win; this only spares a local run from exporting
# everything by hand, exactly as the orchestrator and runtime do.
load_dotenv(os.path.join(BASE_DIR, ".env"))


def require_env(key: str, default:str=None) -> str:
    value = os.getenv(key, default)
    if value is None:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return value


# Inference host: one IP serves the LLM (8001), embeddings and reranking
# (8003), matching orchestrator/app/core/config.py so both services move
# together when the box is replaced.
EC2_INFERENCE_BASE_IP = require_env("EC2_INFERENCE_BASE_IP", "")

# Embeddings are served remotely. Nothing is embedded locally, so this service
# carries no model, no torch, and no GPU expectation.
EMBEDDING_MODEL_BASE = require_env(
    "EMBEDDING_MODEL_BASE",
    f"http://{EC2_INFERENCE_BASE_IP}:8003" if EC2_INFERENCE_BASE_IP else "",
).rstrip("/")
EMBEDDING_MODEL = require_env("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
EMBEDDING_API_KEY = require_env("EMBEDDING_API_KEY", "")
EMBEDDING_TIMEOUT = float(require_env("EMBEDDING_TIMEOUT", "30"))

# Reranking. Off for playbook routing by measurement, not by preference: on the
# 30-question set in tests/rank_eval.py the cross-encoder scored 67% top-1 and
# 87% recall@3, against 83% and 100% for embeddings. ms-marco is trained to
# judge whether a passage answers a query, and a playbook description is not a
# passage - it ranked search_notes first for "Thanks!". Kept configurable
# because it is the right tool for ranking note chunks, just not routing.
RERANKER_API_BASE = require_env(
    "RERANKER_API_BASE",
    f"http://{EC2_INFERENCE_BASE_IP}:8003" if EC2_INFERENCE_BASE_IP else "",
).rstrip("/")
RERANKER_API_KEY = require_env("RERANKER_API_KEY", EMBEDDING_API_KEY)
RERANKER_TIMEOUT = float(require_env("RERANKER_TIMEOUT", "30"))
PLAYBOOK_RERANK_ENABLED = require_env("PLAYBOOK_RERANK_ENABLED", "false").lower() == "true"
# Above this many playbooks, embeddings shortlist first and the cross-encoder
# only reranks the shortlist; at or below it, every playbook is reranked.
RERANK_POOL_LIMIT = int(require_env("RERANK_POOL_LIMIT", "50"))
PLAYBOOK_SEARCH_LIMIT = int(require_env("PLAYBOOK_SEARCH_LIMIT", "5"))

# How many playbooks the selector LLM is willing to read at once. At or below
# this count every playbook is a candidate and semantic search is skipped
# entirely; above it, search narrows the catalog to this many.
PLAYBOOK_CANDIDATE_LIMIT = int(require_env("PLAYBOOK_CANDIDATE_LIMIT", "7"))
