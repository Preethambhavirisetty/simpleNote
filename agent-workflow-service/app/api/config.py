import os

from dotenv import load_dotenv


load_dotenv()


SERVICE_HOST = os.getenv("AGENT_WORKFLOW_HOST", "0.0.0.0")
SERVICE_PORT = int(os.getenv("AGENT_WORKFLOW_PORT", "5453"))
SERVICE_API_KEY = (os.getenv("AGENT_WORKFLOW_API_KEY") or os.getenv("AGENT_API_KEY") or "").strip()

LLM_API_BASE_GENERAL = (os.getenv("LLM_API_BASE_GENERAL") or os.getenv("LLM_API_BASE") or "http://127.0.0.1:8001/v1").strip()
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "reasoner")
LLM_SEND_AUTH_HEADER = os.getenv("LLM_SEND_AUTH_HEADER", "true").strip().lower() in {"1", "true", "yes", "on"}
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))
LLM_TOP_P = float(os.getenv("LLM_TOP_P", "0.9"))
LLM_TOP_K = int(os.getenv("LLM_TOP_K", "40"))
LLM_SEED = int(os.getenv("LLM_SEED", "42"))

MCP_URL = os.getenv("MCP_URL", "")
MCP_AUTH_TOKEN = os.getenv("MCP_AUTH_TOKEN", "")

AGENT_CONFIG_DIR = (os.getenv("AGENT_CONFIG_DIR") or "").strip()
ALLOWED_UPSTREAM_HOSTS = {
    item.strip().lower()
    for item in (os.getenv("ALLOWED_UPSTREAM_HOSTS") or "10.201.62.184,localhost,127.0.0.1,::1").split(",")
    if item.strip()
}

DEFAULT_EXPLORATION_PROFILE = (os.getenv("DEFAULT_EXPLORATION_PROFILE") or "quick").strip().lower()
if DEFAULT_EXPLORATION_PROFILE not in {"quick", "heavy"}:
    DEFAULT_EXPLORATION_PROFILE = "quick"

