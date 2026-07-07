from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from app.agent_workflow.artifact_store import CrossTurnArtifactStore, is_cross_turn_persistence_active


def test_persistence_requires_redis_url_and_flag():
    with patch("app.agent_workflow.artifact_store.resolve_redis_url", return_value=""):
        assert not is_cross_turn_persistence_active(enabled=True)
    with patch("app.agent_workflow.artifact_store.resolve_redis_url", return_value="redis://127.0.0.1:6379/0"):
        assert is_cross_turn_persistence_active(enabled=True)
        assert not is_cross_turn_persistence_active(enabled=False)


def test_artifact_store_round_trip():
    client = MagicMock()
    stored: dict[str, str] = {}

    def _setex(key, ttl, value):
        stored[key] = value

    def _get(key):
        return stored.get(key)

    client.setex.side_effect = _setex
    client.get.side_effect = _get

    store = CrossTurnArtifactStore("redis://127.0.0.1:6379/0")
    with patch.object(store, "_redis", return_value=client):
        artifacts = [{"tool": "list_dashboards", "summary": "32 dashboards", "raw_ref": {"total": 32}}]
        store.save("session-1", artifacts, ttl_seconds=3600)
        loaded = store.load("session-1")

    assert loaded == artifacts
    payload = json.loads(stored["agent-workflow:session-artifacts:session-1"])
    assert payload["artifacts"][0]["tool"] == "list_dashboards"
