import os
import tiktoken

enc = tiktoken.get_encoding("cl100k_base")

def count_tokens(text):
    return len(enc.encode(text))

def build_llm_messages(system_prompt: str, text:str):
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": text}
    ]

def require_env(key: str, default:str=None) -> str:
    value = os.getenv(key, default)
    if value is None:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return value