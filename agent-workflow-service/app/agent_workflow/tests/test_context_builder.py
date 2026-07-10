from __future__ import annotations

from app.agent_workflow.config import AgentConfig, AgentPolicy, McpConfig, TruncationPolicy, LlmConfig, load_agent_config
from app.agent_workflow.context.builder import ContextBuilder
from app.agent_workflow.state import AgentState
from app.agent_workflow.util.tokens import count_tokens


def test_context_builder_respects_budget():
    llm_config = LlmConfig(
        base_url="http://localhost:8001/v1",
        api_key="FAKE-API-KEY",
        model="LOCAL-MODEL"
    )

    config = AgentConfig(
        name="test",
        prompts={},
        llm=llm_config,
        mcp=McpConfig(),
        policy=AgentPolicy(max_context_tokens=200, truncation=TruncationPolicy()),
        base_dir=__import__("pathlib").Path("."),
    )
    state: AgentState = {
        "user_query": "find SLA mentions",
        "plan": {"goal": "search", "steps": [{"title": "Search", "action": "search docs"}]},
        "artifacts": [
            {
                "tool": "search_documents",
                "summary": "x" * 5000,
                "composite_score": 0.9,
                "scores": {"relevance": 0.9, "freshness": 1, "uniqueness": 1, "actionability": 0.5},
            }
        ],
    }
    messages = ContextBuilder(config).build(state, "executor")
    total = sum(count_tokens(m["content"]) for m in messages)
    assert total <= config.policy.max_context_tokens + 50


def test_load_default_agent_config():
    path = __import__("pathlib").Path(__file__).resolve().parents[1] / "agents" / "default.yaml"
    config = load_agent_config(path)
    assert config.name == "default-agent"
    assert config.prompt_text("planner")
    assert config.policy.max_executor_iterations == 16
    assert config.policy.max_context_tokens == 48000
    assert config.policy.truncation.max_artifact_chars == 20000
    assert config.policy.executor.choose_action_max_tokens == 2000
    assert config.policy.finalizer.max_tokens == 4000


def test_format_history_uses_head_and_tail_preview():
    from pathlib import Path

    from app.agent_workflow.config import AgentConfig, AgentPolicy, McpConfig, TruncationPolicy, LlmConfig

    config = AgentConfig(
        name="test",
        prompts={},
        llm=LlmConfig(base_url="http://localhost:8001/v1", api_key="FAKE-API-KEY", model="LOCAL-MODEL"),
        mcp=McpConfig(),
        policy=AgentPolicy(truncation=TruncationPolicy()),
        base_dir=Path(__file__).resolve().parents[1],
    )
    builder = ContextBuilder(config)
    # Long enough to exceed head+tail+24 so the middle-omit actually triggers.
    content = ("START-" + ("x" * 1000) + "-END")
    rendered = builder._format_history([{"role": "user", "content": content}], {"runtime_context": {"follow_up": True}})
    assert "START-" in rendered
    assert "-END" in rendered
    assert "...[middle omitted]..." in rendered
    assert content not in rendered


def test_context_builder_omits_history_unless_follow_up():
    from pathlib import Path

    from app.agent_workflow.config import AgentConfig, AgentPolicy, McpConfig, TruncationPolicy, LlmConfig

    config = AgentConfig(
        name="test",
        prompts={},
        llm=LlmConfig(base_url="http://localhost:8001/v1", api_key="FAKE-API-KEY", model="LOCAL-MODEL"),
        mcp=McpConfig(),
        policy=AgentPolicy(truncation=TruncationPolicy()),
        base_dir=Path(__file__).resolve().parents[1],
    )
    builder = ContextBuilder(config)
    state: AgentState = {
        "user_query": "new question",
        "plan": {"goal": "answer", "steps": [{"title": "Search", "action": "search"}]},
        "messages": [{"role": "user", "content": "old unrelated topic"}],
        "runtime_context": {},
    }
    fresh = "\n".join(message["content"] for message in builder.build(state, "planner"))
    assert "old unrelated topic" not in fresh

    state["runtime_context"] = {"follow_up": True}
    follow_up = "\n".join(message["content"] for message in builder.build(state, "planner"))
    assert "old unrelated topic" in follow_up


def test_context_builder_shows_stop_condition_for_current_executor_step():
    from pathlib import Path

    from app.agent_workflow.config import AgentConfig, AgentPolicy, McpConfig, TruncationPolicy, LlmConfig

    config = AgentConfig(
        name="test",
        prompts={},
        llm=LlmConfig(base_url="http://localhost:8001/v1", api_key="FAKE-API-KEY", model="LOCAL-MODEL"),
        mcp=McpConfig(),
        policy=AgentPolicy(truncation=TruncationPolicy()),
        base_dir=Path(__file__).resolve().parents[1],
    )
    builder = ContextBuilder(config)
    state: AgentState = {
        "user_query": "list dashboards",
        "current_step_index": 0,
        "plan": {
            "goal": "list",
            "steps": [
                {
                    "title": "List",
                    "action": "call list_dashboards",
                    "stop_condition": "at least one dashboard returned",
                }
            ],
        },
    }
    content = "\n".join(message["content"] for message in builder.build(state, "executor"))
    assert "Stop when: at least one dashboard returned" in content
