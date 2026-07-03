import logging

from llama_index.core import Settings
from llama_index.llms.openai_like import OpenAILike

from app.core.config import (
    CHUNK_OVERLAP,
    LLM_API_BASE,
    LLM_API_KEY,
    LLM_CONTEXT_WINDOW,
    LLM_SUMMARIZER_MODEL,
    MAX_CHUNK_SIZE,
)
from app.core.embeddings import RemoteEmbeddingService, RemoteOpenAIEmbedding


log = logging.getLogger(__name__)

_SETTINGS_INITIALIZED = False


def init_llama_index_settings() -> None:
    global _SETTINGS_INITIALIZED
    if _SETTINGS_INITIALIZED:
        return

    # Settings.embed_model is required by SemanticSplitterNodeParser (semantic chunking).
    # The adapter bridges the remote HTTP embedding service to LlamaIndex's BaseEmbedding interface.
    Settings.embed_model = RemoteOpenAIEmbedding(service=RemoteEmbeddingService())

    Settings.llm = OpenAILike(
        api_base=LLM_API_BASE,
        api_key=LLM_API_KEY,
        model=LLM_SUMMARIZER_MODEL,
        context_window=LLM_CONTEXT_WINDOW,
        is_chat_model=True,
        temperature=0.1,
        max_tokens=512,
        is_function_calling_model=False,
        timeout=300.0,
    )

    Settings.chunk_size = MAX_CHUNK_SIZE
    Settings.chunk_overlap = CHUNK_OVERLAP

    _SETTINGS_INITIALIZED = True


def is_llama_index_settings_initialized() -> bool:
    return _SETTINGS_INITIALIZED
