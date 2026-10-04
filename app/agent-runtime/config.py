import os
from urllib.parse import urlparse

from dotenv import load_dotenv

import failures

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Real environment variables win: a container sets them directly, and this file
# is only here so a local run does not need every value exported by hand.
load_dotenv(os.path.join(BASE_DIR, ".env"))


def require_env(key: str, default: str | None = None) -> str:
    value = os.getenv(key, default)
    if value is None or not value.strip():
        raise RuntimeError(f"Missing required environment variable: {key}")
    return value


def require_https_url(key: str) -> str:
    value = require_env(key).rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise RuntimeError(f"{key} must be a valid https:// URL")
    return value


# One host serves the LLM (8001) and embeddings/reranking (8003), matching
# orchestrator/app/core/config.py. Pinning a full URL here is how this service
# ended up on a dead IP while the orchestrator had already moved.
LLM_API_BASE = require_https_url("LLM_API_BASE")
LLM_API_KEY = require_env("LLM_API_KEY")
LLM_SUMMARIZER_MODEL = require_env("LLM_SUMMARIZER_MODEL")

# agent-domain: the declarative catalog of playbooks, operations, and mappings.
DOMAIN_API_BASE = require_env("DOMAIN_API_BASE", "http://agent-domain:8000")
DOMAIN_API_KEY = require_env("DOMAIN_API_KEY")
DOMAIN_TIMEOUT = float(require_env("DOMAIN_TIMEOUT", "10"))

# How the router decides. "single": one call picks playbook and plan together.
# "split": one call picks the playbook, a second picks the plan from only that
# playbook's plans. Split costs a second round trip and cannot reconsider the
# playbook; single keeps the whole decision in one coherent judgement.
PLAYBOOK_SELECTION_MODE = require_env("PLAYBOOK_SELECTION_MODE", "single")

# MCP servers by the name mappings use in agent-domain's `server:` field.
# MCP_SERVERS="notelite=http://agent-mcp:8000/mcp,other=http://..."
MCP_SERVERS = {
    name.strip(): url.strip()
    for name, _, url in (
        entry.partition("=")
        for entry in require_env(
            "MCP_SERVERS", "notelite=http://agent-mcp:8000/mcp"
        ).split(",")
        if entry.strip()
    )
    if name.strip() and url.strip()
}
MCP_TIMEOUT = float(require_env("MCP_TIMEOUT", "60"))
RUN_CONCURRENCY = int(require_env("RUN_CONCURRENCY", "20"))

# Off until a run can pause for approval and resume through the API. Routing
# still selects the mutating playbook, so logs and evals stay honest; the plan
# just declines instead of acting. Flip to "true" when resume exists.
MUTATIONS_ENABLED = require_env("MUTATIONS_ENABLED", "false").lower() == "true"
# The refusal wording lives in the shared catalog so the runtime, the stream,
# and the persisted message all say the same thing.
MUTATIONS_DISABLED_MESSAGE = require_env(
    "MUTATIONS_DISABLED_MESSAGE", failures.ACTION_NOT_SUPPORTED.message
)

# Shared secret the orchestrator sends as X-API-Key.
AGENT_API_KEY = require_env("AGENT_WORKFLOW_API_KEY")
# Structured run logging into the agentlog service (observability/). Optional:
# with the SDK absent or the collector down, every log call is a no-op.
AGENTLOG_ENABLED = require_env("AGENTLOG_ENABLED", "true").lower() == "true"
AGENTLOG_ENDPOINT = require_env("AGENTLOG_ENDPOINT", "http://agentlog-api:8000")
AGENTLOG_API_KEY = require_env("AGENTLOG_API_KEY")
