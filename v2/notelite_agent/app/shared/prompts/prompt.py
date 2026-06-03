from __future__ import annotations

from collections.abc import Sequence

from app.shared.prompts.prompt_manager import prompt_manager
from app.shared.utils import count_tokens


def get_group_summary_system_prompt() -> str:
    return prompt_manager.get_text("summarizer", "group_system")


def get_final_summary_system_prompt() -> str:
    return prompt_manager.get_text("summarizer", "final_system")


def get_generate_questions_system_prompt(generate_count: int) -> str:
    return prompt_manager.render_text(
        "summarizer", "questions_system", generate_count=generate_count,
    )


def get_keyword_dedup_system_prompt() -> str:
    return prompt_manager.get_text("classify", "keyword_dedup_system")


def get_entity_dedup_system_prompt() -> str:
    return prompt_manager.get_text("classify", "entity_dedup_system")


def build_messages(
    query: str,
    history: Sequence[dict[str, str]],
    context_texts: list[str],
) -> list[dict[str, str]]:
    system_content = prompt_manager.get_text("chat_system", "system")
    if context_texts:
        context_block = "\n\n---\n\n".join(context_texts)
        context_prompt = prompt_manager.render_text(
            "chat_system", "context_template", context=context_block,
        )
        system_content = f"{system_content}\n\n{context_prompt}"

    messages: list[dict[str, str]] = [{"role": "system", "content": system_content}]
    messages.extend(history)
    messages.append({"role": "user", "content": query})
    return messages


def estimate_prompt_tokens(messages: Sequence[dict[str, str]]) -> int:
    # ~4 overhead tokens per message beyond content (chat template overhead)
    return sum(count_tokens(m.get("content", "")) + 4 for m in messages)


if __name__ == "__main__":
    summary_prompt = get_group_summary_system_prompt()
    print(summary_prompt)