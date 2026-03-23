import os
import logging
from llama_index.core import Settings
from llama_index.llms.openai_like import OpenAILike
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from core.config import (
    LLM_API_BASE,
    LLM_API_KEY,
    LLM_MODEL,
    LLM_CONTEXT_WINDOW,
    EMBEDDING_MODEL,
    EMBEDDING_DEVICE,
    MAX_CHUNK_SIZE,
    CHUNK_OVERLAP,
)

_SETTINGS_INITIALIZED = False


def _configure_runtime_logging():
    """Silence verbose HF/transformers progress and warning logs."""
    os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    os.environ["TRANSFORMERS_VERBOSITY"] = "error"
    os.environ["TQDM_DISABLE"] = "1"

    try:
        from transformers.utils import logging as transformers_logging
        transformers_logging.set_verbosity_error()
        transformers_logging.disable_progress_bar()
    except Exception:
        pass

    logging.getLogger("transformers").setLevel(logging.ERROR)
    logging.getLogger("sentence_transformers").setLevel(logging.ERROR)
    logging.getLogger("huggingface_hub").setLevel(logging.ERROR)


def init_llama_index_settings():
    """Initialize global LlamaIndex settings for local llama.cpp + embeddings.

    OpenAILike is the right class for any local OpenAI-compatible server:
      • Accepts arbitrary model names (no validation against OpenAI's model list).
      • Exposes is_chat_model so complete() maps to /v1/chat/completions, which
        is the only generation endpoint the inference server exposes.
      • Passes context_window through to LlamaIndex's chunking pipeline so that
        documents are never split into pieces larger than the model's context.
    """
    global _SETTINGS_INITIALIZED
    if _SETTINGS_INITIALIZED:
        return

    _configure_runtime_logging()

    Settings.llm = OpenAILike(
        api_base=LLM_API_BASE,
        api_key=LLM_API_KEY,
        model=LLM_MODEL,
        is_chat_model=True,       # routes complete() → /v1/chat/completions
        context_window=LLM_CONTEXT_WINDOW,
        temperature=0.4,          # match BALANCED_0 preset for consistent results
        max_tokens=512,
        is_function_calling_model=False,
    )

    Settings.embed_model = HuggingFaceEmbedding(
        model_name=EMBEDDING_MODEL,
        device=EMBEDDING_DEVICE,
        query_instruction="Represent this sentence for searching relevant passages: ",
    )

    Settings.chunk_size    = MAX_CHUNK_SIZE
    Settings.chunk_overlap = CHUNK_OVERLAP
    _SETTINGS_INITIALIZED = True


def is_llama_index_settings_initialized() -> bool:
    return _SETTINGS_INITIALIZED
