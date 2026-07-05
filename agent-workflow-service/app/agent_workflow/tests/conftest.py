from __future__ import annotations

import pytest

from app.agent_workflow.cache import clear_engine_caches


@pytest.fixture(autouse=True)
def _fresh_engine_caches():
    """Each test gets isolated graph/provider caches.

    The compiled graph closes over its llm/tools instances; without this,
    engines built in later tests can observe earlier tests' cached state.
    """
    clear_engine_caches()
    yield
    clear_engine_caches()
