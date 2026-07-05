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
