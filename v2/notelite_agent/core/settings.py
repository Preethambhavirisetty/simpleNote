import os
import logging
from llama_index.core import Settings
from llama_index.llms.openai_like import OpenAILike
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.sparse_embeddings.fastembed import FastEmbedSparseEmbedding
from core.config import (
    LLM_API_BASE,
    LLM_API_KEY,
    LLM_MODEL,
    LLM_CONTEXT_WINDOW,
    EMBEDDING_MODEL,
    SPARSE_EMBEDDING_MODEL,
    EMBEDDING_DEVICE,
    MAX_CHUNK_SIZE,
    CHUNK_OVERLAP,
)

_SETTINGS_INITIALIZED = False


def _materialize_host_ca_bundle_for_openssl() -> None:
    """Copy host-mounted CA file into /tmp before HF/httpx runs.

    Podman bind-mounts of macOS cert bundles can make ssl.load_verify_locations
    raise PermissionError; reading the same path in Python and rewriting to /tmp
    avoids that.
    """
    src = (os.environ.get("SSL_CERT_FILE") or "").strip()
    if not src or not os.path.isfile(src):
        return
    dest = "/tmp/notelite-host-ca-bundle.pem"
    if os.path.abspath(src) == os.path.abspath(dest):
        return
    try:
        with open(src, "rb") as f:
            data = f.read()
        if not data.strip():
            return
        with open(dest, "wb") as f:
            f.write(data)
        os.chmod(dest, 0o644)
    except OSError:
        return
    os.environ["SSL_CERT_FILE"] = dest
    os.environ["REQUESTS_CA_BUNDLE"] = dest
    os.environ["CURL_CA_BUNDLE"] = dest


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

    _materialize_host_ca_bundle_for_openssl()
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
        timeout=300.0,            # cold model load (~30s) + inference can exceed default 60s
    )

    # Use the image-baked HuggingFace cache when present; fall back to /tmp for
    # local runs where the container env is not set.
    _cache_dir = os.environ.get("HF_HOME", "/tmp/hf_cache")
    os.makedirs(_cache_dir, exist_ok=True)

    Settings.embed_model = HuggingFaceEmbedding(
        model_name=EMBEDDING_MODEL,
        device=EMBEDDING_DEVICE,
        query_instruction="Represent this sentence for searching relevant passages: ",
        cache_folder=_cache_dir,
    )

    Settings.sparse_model = FastEmbedSparseEmbedding(model_name=SPARSE_EMBEDDING_MODEL)

    Settings.chunk_size    = MAX_CHUNK_SIZE
    Settings.chunk_overlap = CHUNK_OVERLAP
    _SETTINGS_INITIALIZED = True


def is_llama_index_settings_initialized() -> bool:
    return _SETTINGS_INITIALIZED
