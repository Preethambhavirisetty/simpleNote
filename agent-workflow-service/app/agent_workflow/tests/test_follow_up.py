from __future__ import annotations

from app.agent_workflow.follow_up import (
    apply_follow_up_runtime_context,
    follow_up_approval_gaps,
    follow_up_tool_recall_missing,
    is_follow_up_query,
    resolve_follow_up_policy,
)


def test_follow_up_query_detects_table_request():
    history = [{"role": "assistant", "content": "Here are all dashboards..."}]
    assert is_follow_up_query("put them in a table with serial numbers", history)


def test_follow_up_query_detects_refinement_without_pronouns():
    history = [
        {
            "role": "user",
            "content": "autopod_rows_availability, site=RTP, show rows with available power under 30 kW",
        },
        {"role": "assistant", "content": "No single bucket covers under 30 kW; here are the closest filters..."},
    ]
    follow_up = (
        "if there is no explicit filter for less than 30, "
        "give me all rows from all from 0 to under 30"
    )
    assert is_follow_up_query(follow_up, history)


def test_follow_up_query_detects_topic_anchor_overlap():
    history = [{"role": "user", "content": "autopod_rows_availability site=RTP under 30 kW"}]
    assert is_follow_up_query("show rows under 30 with populated tokens", history)


def test_follow_up_query_detects_single_identifier_and_this_pronoun():
    # Regression: a follow-up naming exactly one distinctive identifier (plus the
    # pronoun "this") was misclassified as a new topic, wrongly clearing memory.
    history = [
        {"role": "user", "content": "tell me about the autopod_rows_availability dashboard"},
        {"role": "assistant", "content": "The autopod_rows_availability dashboard shows power."},
    ]
    assert is_follow_up_query(
        "let use this autopod_rows_availability dashboard to see if power is available", history
    )
    assert is_follow_up_query("what about this one", history)  # bare "this" pronoun
    assert not is_follow_up_query("what is the weather in paris", history)  # genuine new topic


def test_known_memory_entity_makes_query_a_follow_up():
    # Naming an entity the session remembers is a follow-up even when no
    # pronoun/anchor regex fires and the entity isn't in the recent history
    # window (long conversations scroll old anchors out).
    history = [{"role": "user", "content": "ok thanks"}, {"role": "assistant", "content": "welcome"}]
    query = "check power in aiera-power now"  # hyphenated: no snake_case anchor match
    assert not is_follow_up_query(query, history)
    assert is_follow_up_query(query, history, known_entities=["aiera-power"])
    # Short/generic values never count.
    assert not is_follow_up_query("check rtp", history, known_entities=["rtp"])


def test_memory_entity_values_extracts_slot_values():
    from app.agent_workflow.conversation_memory import memory_entity_values

    memory = {
        "dashboard": {"value": "autopod_rows_availability", "turn": 2},
        "bad": "not-a-slot",
        "empty": {"value": "", "turn": 1},
    }
    assert memory_entity_values(memory) == ["autopod_rows_availability"]
    assert memory_entity_values(None) == []


def test_resolve_policy_requires_recall_without_app_specific_tool_names():
    # The app-specific keyword->tool map was removed; a follow-up needing fresh
    # evidence requires *some* tool call, not a hardcoded named tool.
    history = [{"role": "user", "content": "tell me about the fleet_power dashboard"}]
    policy = resolve_follow_up_policy(
        query="show this fleet_power dashboard again",
        history=history,
        persisted_artifacts=[],
        persistence_active=False,
        require_tool_on_follow_up=True,
    )
    assert policy.is_follow_up and policy.require_tool_recall
    assert policy.required_tools == frozenset()


def test_without_persistence_follow_up_requires_tool_recall():
    history = [{"role": "assistant", "content": "Here are dashboards..."}]
    policy = resolve_follow_up_policy(
        query="put them in a table",
        history=history,
        persisted_artifacts=[],
        persistence_active=False,
        require_tool_on_follow_up=True,
    )
    assert policy.is_follow_up
    assert policy.require_tool_recall
    runtime = apply_follow_up_runtime_context({}, policy)
    assert runtime["require_tools"] is True
    assert runtime["follow_up"] is True


def test_with_persisted_artifacts_follow_up_does_not_require_recall():
    history = [{"role": "assistant", "content": "Here are dashboards..."}]
    artifacts = [{"tool": "list_dashboards", "summary": "32 dashboards", "raw_ref": {"items": []}}]
    policy = resolve_follow_up_policy(
        query="put them in a table",
        history=history,
        persisted_artifacts=artifacts,
        persistence_active=True,
        require_tool_on_follow_up=True,
    )
    assert policy.is_follow_up
    assert not policy.require_tool_recall
    runtime = apply_follow_up_runtime_context({}, policy)
    assert "require_tools" not in runtime


def test_follow_up_fresh_recall_not_satisfied_by_persisted_artifacts_only():
    state = {
        "runtime_context": {
            "follow_up": True,
            "require_tools": True,
            "require_fresh_tool_recall": True,
            "persisted_artifact_count": 2,
        },
        "artifacts": [{"tool": "list_dashboards", "summary": "31 dashboards"}],
        "tool_calls": [],
    }
    missing = follow_up_tool_recall_missing(state)
    assert missing
    assert "fresh tool call" in missing[0].lower()


def test_follow_up_persisted_reuse_does_not_require_fresh_call():
    state = {
        "runtime_context": {
            "follow_up": True,
            "persisted_reuse": True,
            "persisted_artifact_count": 2,
        },
        "artifacts": [{"tool": "get_dashboard", "summary": "16 panels"}],
        "tool_calls": [],
    }
    assert not follow_up_tool_recall_missing(state)
    state = {
        "runtime_context": {
            "follow_up": True,
            "require_tools": True,
            "follow_up_required_tools": ["list_dashboards"],
        },
        "artifacts": [],
        "tool_calls": [],
    }
    missing = follow_up_tool_recall_missing(state)
    assert missing
    assert "list_dashboards" in missing[0]


def test_follow_up_reviewer_rejects_ungrounded_answer():
    state = {
        "runtime_context": {
            "follow_up": True,
            "require_tools": True,
            "follow_up_required_tools": ["list_dashboards"],
        },
        "artifacts": [],
        "tool_calls": [],
        "draft_answer": "Here is a table...",
    }
    gaps = follow_up_approval_gaps(state)
    assert gaps
