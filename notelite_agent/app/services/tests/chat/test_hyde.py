"""HyDE budget alignment and the disable switch."""
from unittest.mock import patch

from app.core.config import HYDE_MAX_TOKENS, HYDE_TIMEOUT
from app.services.chat.pipeline import retrieval_pipeline
from app.services.chat.pipeline.retrieval_pipeline import PreparedQuery, generate_hyde


def prepared():
    return PreparedQuery(original_query="What did I plan?", search_query="What did I plan?")


def test_timeout_covers_the_token_budget():
    """A non-streaming completion must be able to finish inside its timeout:
    at a conservative ~20 tok/s the budget must fit, or HyDE times out on
    every query and only adds latency."""
    assert HYDE_TIMEOUT >= HYDE_MAX_TOKENS / 20


def test_disabled_skips_the_llm_call_entirely():
    def fail(*args, **kwargs):
        raise AssertionError("LLM must not be called when HyDE is disabled")

    with patch.object(retrieval_pipeline, "HYDE_ENABLED", False), \
         patch.object(retrieval_pipeline, "llm_call_general", fail):
        assert generate_hyde(prepared()) == (None, "disabled")


def test_llm_failure_still_falls_back_cleanly():
    with patch.object(retrieval_pipeline, "HYDE_ENABLED", True), \
         patch.object(retrieval_pipeline, "llm_call_general", side_effect=TimeoutError):
        value, status = generate_hyde(prepared())

    assert value is None
    assert status == "fallback:TimeoutError"
