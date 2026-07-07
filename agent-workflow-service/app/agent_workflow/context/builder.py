from __future__ import annotations

import json
from typing import Any, Literal

from app.agent_workflow.config import AgentConfig
from app.agent_workflow.state import AgentState, Artifact
from app.agent_workflow.util.tokens import count_tokens

Role = Literal["planner", "executor", "reviewer"]


class ContextBuilder:
    """Builds role-specific LLM messages from workflow state."""

    def __init__(self, config: AgentConfig):
        """Initialize this object with its runtime dependencies."""
        self.config = config

    def build(self, state: AgentState, role: Role) -> list[dict[str, str]]:
        """Build the prompt messages for a planner, executor, or reviewer LLM call."""
        system = self.config.prompt_text(role)
        contract = self._contract_prompt()
        if contract:
            system = f"{system}\n\n{contract}"
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
            sections.append(
                (
                    60,
                    f"Recent tool calls:\n{self._format_tool_calls(tool_calls[-self.config.policy.context.max_tool_calls_in_prompt :])}",
                )
            )

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

    def _contract_prompt(self) -> str:
        """Load the shared contract prompt appended to every role system message."""
        path = self.config.base_dir / "prompts" / "contract.md"
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
        return ""

    def _fit_budget(self, sections: list[tuple[int, str]], system: str) -> str:
        """Select the highest-priority context sections that fit the token budget."""
        limits = self.config.policy.context
        max_tokens = self.config.policy.max_context_tokens
        used = count_tokens(system) + limits.system_budget_padding
        ordered = sorted(sections, key=lambda item: item[0], reverse=True)
        chosen: list[str] = []
        for _priority, text in ordered:
            tokens = count_tokens(text)
            if used + tokens <= max_tokens:
                chosen.append(text)
                used += tokens
                continue
            remaining = max_tokens - used
            if text.startswith("Artifacts:\n") and remaining >= limits.min_artifact_budget_tokens:
                trimmed = self._trim_section_to_token_budget(text, remaining, limits.trim_section_min_chars)
                if trimmed:
                    chosen.append(trimmed)
                    used += count_tokens(trimmed)
        return "\n\n---\n\n".join(chosen)

    @staticmethod
    def _trim_section_to_token_budget(text: str, token_budget: int, min_chars: int) -> str:
        """Trim a long context section while preserving whole artifact bullets."""
        if token_budget <= 0:
            return ""
        max_chars = max(min_chars, token_budget * 4)
        if len(text) <= max_chars:
            return text
        return text[:max_chars].rsplit("\n- ", 1)[0].rstrip() + "\n- [truncated] additional artifacts omitted due to context budget"

    def _format_plan(self, plan: dict[str, Any], step_index: int, role: Role) -> str:
        """Format plan for inclusion in LLM context."""
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
        """Format tools for inclusion in LLM context."""
        lines = []
        for tool in tools[: self.config.policy.context.max_tools_in_prompt]:
            schema = tool.get("input_schema") or tool.get("inputSchema") or {}
            lines.append(
                f"- {tool.get('name')} ({tool.get('title', '')}, score={tool.get('score', 0):.2f}): "
                f"{tool.get('description', '')}\n  inputSchema: {json.dumps(schema, ensure_ascii=False)}"
            )
        return "\n".join(lines)

    def _format_artifacts(self, artifacts: list[Artifact]) -> str:
        """Format artifacts for inclusion in LLM context."""
        limits = self.config.policy.context
        max_summary_chars = max(
            limits.artifact_summary_min_chars,
            int(self.config.policy.truncation.max_artifact_chars * limits.artifact_summary_ratio),
        )
        lines = []
        for artifact in artifacts[: limits.max_artifacts_in_prompt]:
            scores = artifact.get("scores") or {}
            source = artifact.get("source_ref") or {}
            lines.append(
                f"- [{artifact.get('tool')}] score={artifact.get('composite_score', 0):.2f} "
                f"(r={scores.get('relevance', 0)}, f={scores.get('freshness', 0)}, "
                f"u={scores.get('uniqueness', 0)}, a={scores.get('actionability', 0)}) "
                f"source={json.dumps(source) if source else '{}'}\n"
                f"  {str(artifact.get('summary', ''))[:max_summary_chars]}"
            )
        return "\n".join(lines)

    def _format_tool_calls(self, records: list[dict[str, Any]]) -> str:
        """Format tool calls for inclusion in LLM context."""
        return "\n".join(
            f"- {r.get('name')} ({r.get('status')}): {r.get('args_preview', '')}" for r in records
        )

    def _truncate_message_preview(self, content: str) -> str:
        limits = self.config.policy.context
        head = limits.history_preview_head_chars
        tail = limits.history_preview_tail_chars
        if len(content) <= head + tail + 24:
            return content
        return f"{content[:head]}\n...[middle omitted]...\n{content[-tail:]}"

    def _format_history(self, messages: list[dict[str, Any]]) -> str:
        """Format history for inclusion in LLM context."""
        lines = []
        for message in messages[-self.config.policy.context.max_history_messages :]:
            content = str(message.get("content", ""))
            lines.append(f"{message.get('role', 'user')}: {self._truncate_message_preview(content)}")
        return "\n".join(lines)
