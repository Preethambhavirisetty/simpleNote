import logging
import os

from llama_index.core import Settings
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.llms.openai_like import OpenAILike
from llama_index.sparse_embeddings.fastembed import FastEmbedSparseEmbedding

from app.core.config import (
    CHUNK_OVERLAP,
    EMBEDDING_DEVICE,
    EMBEDDING_MODEL,
    LLM_API_BASE,
    LLM_API_KEY,
    LLM_CONTEXT_WINDOW,
    LLM_MODEL,
    MAX_CHUNK_SIZE,
    SPARSE_EMBEDDING_MODEL,
)


log = logging.getLogger(__name__)

_SETTINGS_INITIALIZED = False
MODEL_CACHE_DIR = os.path.expanduser(os.getenv("MODEL_CACHE_DIR", "~/.my_model_cache"))


def _configure_runtime_logging():
    """Silence verbose HF/transformers progress and warning logs."""
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
    os.environ.setdefault("TQDM_DISABLE", "1")

    try:
        from transformers.utils import logging as transformers_logging

        transformers_logging.set_verbosity_error()
        transformers_logging.disable_progress_bar()
    except Exception:
        log.debug("Could not configure transformers logging", exc_info=True)

    logging.getLogger("transformers").setLevel(logging.ERROR)
    logging.getLogger("sentence_transformers").setLevel(logging.ERROR)
    logging.getLogger("huggingface_hub").setLevel(logging.ERROR)


def _configure_model_cache():
    """Point HuggingFace and sentence-transformers at a persistent cache."""
    os.makedirs(MODEL_CACHE_DIR, exist_ok=True)
    os.environ.setdefault("TORCH_HOME", MODEL_CACHE_DIR)
    os.environ.setdefault("HF_HOME", MODEL_CACHE_DIR)
    os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", MODEL_CACHE_DIR)


def _embedding_model_identifier() -> str:
    """Use a baked local model copy when present; otherwise use the configured HF model id."""
    local_model_path = os.path.join(MODEL_CACHE_DIR, EMBEDDING_MODEL.replace("/", "_"))
    if os.path.exists(os.path.join(local_model_path, "config.json")):
        log.info("Loading embedding model from local cache: %s", local_model_path)
        return f"local:{local_model_path}"

    log.info("Loading embedding model: %s", EMBEDDING_MODEL)
    return EMBEDDING_MODEL


def init_llama_index_settings():
    global _SETTINGS_INITIALIZED
    if _SETTINGS_INITIALIZED:
        return

    _configure_runtime_logging()
    _configure_model_cache()

    Settings.llm = OpenAILike(
        api_base=LLM_API_BASE,
        api_key=LLM_API_KEY,
        model=LLM_MODEL,
        context_window=LLM_CONTEXT_WINDOW,
        is_chat_model=True,
        temperature=0.1,
        max_tokens=512,
        is_function_calling_model=False,
        timeout=300.0,
    )

    Settings.embed_model = HuggingFaceEmbedding(
        model_name=_embedding_model_identifier(),
        device=EMBEDDING_DEVICE,
        query_instruction="Represent this sentence for searching relevant passages: ",
        cache_folder=MODEL_CACHE_DIR,
    )
    Settings.sparse_model = FastEmbedSparseEmbedding(model_name=SPARSE_EMBEDDING_MODEL)
    Settings.chunk_size = MAX_CHUNK_SIZE
    Settings.chunk_overlap = CHUNK_OVERLAP

    _SETTINGS_INITIALIZED = True


def is_llama_index_settings_initialized() -> bool:
    return _SETTINGS_INITIALIZED
