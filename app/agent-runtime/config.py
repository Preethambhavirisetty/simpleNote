import os

def require_env(key: str, default:str=None) -> str:
    value = os.getenv(key, default)
    if value is None:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return value


LLM_API_BASE = require_env("LLM_API_BASE")
LLM_API_KEY = require_env("LLM_API_KEY")
LLM_SUMMARIZER_MODEL = require_env("LLM_SUMMARIZER_MODEL")