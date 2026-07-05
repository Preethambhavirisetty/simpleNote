from __future__ import annotations

import json
from typing import Any, Literal

from app.agent_workflow.config import AgentConfig
from app.agent_workflow.state import AgentState, Artifact
from app.agent_workflow.util.tokens import count_tokens

Role = Literal["planner", "executor", "reviewer"]


class ContextBuilder:
    def __init__(self, config: AgentConfig):
        self.config = config

    def build(self, state: AgentState, role: Role) -> list[dict[str, str]]:
        system = self.config.prompt_text(role)
        if self.config.policy.instructions:
            system = f"{system}\n\n## Agent instructions\n{self.config.policy.instructions}"

        sections: list[tuple[int, str]] = []
        sections.append((100, f"User request:\n{state.get('user_query', '')}"))

        plan = state.get("plan") or {}
        if plan:
            sections.append((95, f"Plan:\n{self._format_plan(plan, state.get('current_step_index', 0), role)}"))

        if role == "executor" and state.get("candidate_tools"):
            sections.append((80, f"Candidate tools:\n{self._format_tools(state['candidate_tools'])}"))

        artifacts = sorted(
            state.get("artifacts") or [],
            key=lambda a: float(a.get("composite_score") or 0.0),
            reverse=True,
        )
        if artifacts:
            sections.append((70, f"Artifacts:\n{self._format_artifacts(artifacts)}"))

        tool_calls = state.get("tool_calls") or []
        if tool_calls:
            sections.append((60, f"Recent tool calls:\n{self._format_tool_calls(tool_calls[-5:])}"))

        if state.get("review_feedback") and role in ("executor", "planner"):
            sections.append((90, f"Reviewer feedback:\n{state['review_feedback']}"))

        history = state.get("messages") or []
        if history:
            sections.append((50, f"Conversation history:\n{self._format_history(history)}"))

        if role == "reviewer":
            sections.append((85, f"Draft answer:\n{state.get('draft_answer', '')}"))

        body = self._fit_budget(sections, system)
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": body},
        ]

    def _fit_budget(self, sections: list[tuple[int, str]], system: str) -> str:
        max_tokens = self.config.policy.max_context_tokens
        used = count_tokens(system) + 50
        ordered = sorted(sections, key=lambda item: item[0], reverse=True)
        chosen: list[str] = []
        for _priority, text in ordered:
            tokens = count_tokens(text)
            if used + tokens <= max_tokens:
                chosen.append(text)
                used += tokens
                continue
            remaining = max_tokens - used
            if text.startswith("Artifacts:\n") and remaining >= 200:
                trimmed = self._trim_section_to_token_budget(text, remaining)
                if trimmed:
                    chosen.append(trimmed)
                    used += count_tokens(trimmed)
        return "\n\n---\n\n".join(chosen)

    @staticmethod
    def _trim_section_to_token_budget(text: str, token_budget: int) -> str:
        if token_budget <= 0:
            return ""
        max_chars = max(200, token_budget * 4)
        if len(text) <= max_chars:
            return text
        return text[:max_chars].rsplit("\n- ", 1)[0].rstrip() + "\n- [truncated] additional artifacts omitted due to context budget"

    def _format_plan(self, plan: dict[str, Any], step_index: int, role: Role) -> str:
        lines = [f"Goal: {plan.get('goal', '')}"]
        steps = plan.get("steps") or []
        for idx, step in enumerate(steps):
            prefix = ">>" if role == "executor" and idx == step_index else "  "
            hint = f" [tool hint: {step.get('tool_hint')}]" if step.get("tool_hint") else ""
            lines.append(
                f"{prefix} Step {idx + 1}: {step.get('title', '')} — {step.get('action', '')}{hint}"
            )
        criteria = plan.get("acceptance_criteria") or []
        if criteria:
            lines.append("Acceptance criteria:")
            lines.extend(f"- {item}" for item in criteria)
        return "\n".join(lines)

    def _format_tools(self, tools: list[dict[str, Any]]) -> str:
        lines = []
        for tool in tools[:7]:
            schema = tool.get("input_schema") or tool.get("inputSchema") or {}
            lines.append(
                f"- {tool.get('name')} ({tool.get('title', '')}, score={tool.get('score', 0):.2f}): "
                f"{tool.get('description', '')}\n  inputSchema: {json.dumps(schema)[:500]}"
            )
        return "\n".join(lines)

    def _format_artifacts(self, artifacts: list[Artifact]) -> str:
        lines = []
        for artifact in artifacts[:8]:
            scores = artifact.get("scores") or {}
            source = artifact.get("source_ref") or {}
            lines.append(
                f"- [{artifact.get('tool')}] score={artifact.get('composite_score', 0):.2f} "
                f"(r={scores.get('relevance', 0)}, f={scores.get('freshness', 0)}, "
                f"u={scores.get('uniqueness', 0)}, a={scores.get('actionability', 0)}) "
                f"source={json.dumps(source) if source else '{}'}\n"
                f"  {artifact.get('summary', '')[:1200]}"
            )
        return "\n".join(lines)

    def _format_tool_calls(self, records: list[dict[str, Any]]) -> str:
        return "\n".join(
            f"- {r.get('name')} ({r.get('status')}): {r.get('args_preview', '')}" for r in records
        )

    def _format_history(self, messages: list[dict[str, Any]]) -> str:
        lines = []
        for message in messages[-6:]:
            lines.append(f"{message.get('role', 'user')}: {str(message.get('content', ''))[:500]}")
        return "\n".join(lines)
