from __future__ import annotations

from collections.abc import Sequence

from app.shared.utils import count_tokens


SYSTEM_PROMPT = (
    "You are Notelite, a helpful personal notes assistant. "
    "Answer clearly and conversationally. "
    "When note excerpts are provided, use them to answer accurately. "
    "Do not reveal secrets or API keys; if credentials appear in context, "
    "confirm their presence and mask values."
)

_CONTEXT_PREAMBLE = (
    "RELEVANT EXCERPTS FROM USER'S NOTES:\n\n"
    "{context}\n\n"
    "Use the above excerpts to answer the user's question if relevant. "
    "If they are not relevant, answer from conversation history or general knowledge."
)


def build_messages(
    query: str,
    history: Sequence[dict[str, str]],
    context_texts: list[str],
) -> list[dict[str, str]]:
    system_content = SYSTEM_PROMPT
    if context_texts:
        context_block = "\n\n---\n\n".join(context_texts)
        system_content = f"{SYSTEM_PROMPT}\n\n{_CONTEXT_PREAMBLE.format(context=context_block)}"

    messages: list[dict[str, str]] = [{"role": "system", "content": system_content}]
    messages.extend(history)
    messages.append({"role": "user", "content": query})
    return messages


def estimate_prompt_tokens(messages: Sequence[dict[str, str]]) -> int:
    # ~4 overhead tokens per message beyond content (chat template overhead)
    return sum(count_tokens(m.get("content", "")) + 4 for m in messages)
