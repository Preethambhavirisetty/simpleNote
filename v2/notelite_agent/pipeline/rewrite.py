"""Query rewriting for multi-turn conversations.

Rewrites vague follow-up queries (e.g. "what about the second one?") into
self-contained queries (e.g. "what is the second item in my grocery list?")
so vector search can retrieve relevant chunks.

Sample input & request:

Input:
query = "If I want to focus on those to help with that, how can I actually start learning them without spending a fortune?"
history = [
    {
        "role": "user",
        "content": "Hey, I’ve been thinking lately—what’s the actual secret to getting rich? Is it just luck, or is there a trick to it?"
    },
    {
        "role": "assistant",
        "content": "Honestly, I think the 'secret' is usually way less exciting than people hope! Most people who build wealth over time focus on things like consistent saving, learning high-value skills, and playing the long game rather than looking for a quick win."
    },
    {
        "role": "user",
        "content": "That sounds like a lot of work. Isn't there some kind of shortcut or a side hustle that just takes off overnight?"
    },
    {
        "role": "assistant",
        "content": "It’s definitely a grind! While you hear stories about overnight successes, they're pretty rare. Most of the time, those 'overnight' stories are actually the result of years of trial and error. It’s usually about finding a problem people have and solving it better than anyone else."
    }
]
Request:
{
    "model": "llama3.1",
    "messages": [
        {
            "role": "system",
            "content": (
                "Rewrite the user's latest question into a single, self-contained question. Do NOT answer it.\n\n"
                "Rules:\n"
                "- Preserve intent of the user\n"
                "- The output must be a question (ending with ?), never a statement or answer.\n"
                "- Replace pronouns (it, that, they, etc.) with the specific nouns from the conversation.\n"
                "- Keep it concise — one sentence.\n"
                "- If the question is already self-contained, return it exactly as-is.\n"
            )
        },
        {
            "role": "user",
            "content": (
                "History:\n"
                "User: Hey, I’ve been thinking lately—what’s the actual secret to getting rich? Is it just luck, or is there a trick to it?\n"
                "Assistant: Honestly, I think the 'secret' is usually way less exciting than people hope! Most people who build wealth over time focus on things like consistent saving, learning high-value skills, and playing the long game rather than looking for a quick win.\n"
                "User: That sounds like a lot of work. Isn't there some kind of shortcut or a side hustle that just takes off overnight?\n"
                "Assistant: It’s definitely a grind! While you hear stories about overnight successes, they're pretty rare. Most of the time, those 'overnight' stories are actually the result of years of trial and error. It’s usually about finding a problem people have and solving it better than anyone else.\n\n"
                "Latest question: If I want to focus on those to help with that, how can I actually start learning them without spending a fortune?"
            )
        }
    ],
    "max_tokens": 64,
    "temperature": 0.0
}

Sample response:
{
    'id': 'chatcmpl-69e1be45',
    'object': 'chat.completion',
    'created': 1776401989,
    'model': 'llama3.1',
    'choices': [
        {
            'index': 0,
            'message': {
                'role': 'assistant',
                'content': 'How can I start learning consistent saving, high-value skills, and playing the long game without spending a fortune?'
            },
            'finish_reason': 'stop'
        }
    ],
    'usage': {
        'prompt_tokens': 305,
        'completion_tokens': 22,
        'total_tokens': 327
    }
}
"""

from __future__ import annotations
import time
import structlog
from pipeline.llm import llm_call


log = structlog.get_logger()


_REWRITE_SYSTEM_PROMPT = """\
Rewrite the user's latest question into a single, self-contained question. \
Do NOT answer it.

Rules:
- Preserve intent of the user
- The output must be a question (ending with ?), never a statement or answer.
- Replace pronouns (it, that, they, etc.) with the specific nouns from the conversation.
- Keep it concise — one sentence.
- If the question is already self-contained, return it exactly as-is.
"""

_MAX_TOKENS = 64

def rewrite_query(query: str, history: list[dict]) -> tuple[str, int]:
    """Rewrite a follow-up query using conversation history.

    Returns (rewritten_query, latency_ms).
    Falls back to the original query on any error.
    """
    history_block = "\n".join(
        f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
        for m in history[-6:]  # last 3 turns is enough context for rewriting
    )

    log.info(
        "chat.query_rewrite",
        query=query,
        history=history_block,
    )

    t0 = time.monotonic()
    try:
        payload = {
            "model": "llama3.1",
            "messages": [
                {"role": "system", "content": _REWRITE_SYSTEM_PROMPT},
                {"role": "user", "content": f"History:\n{history_block}\n\nLatest question: {query}"},
            ],
            "max_tokens": _MAX_TOKENS,
            "temperature": 0.0,
        }
        resp = llm_call(payload)
        rewritten = resp["choices"][0]["message"]["content"].strip()
        latency_ms = int((time.monotonic() - t0) * 1000)

        if not rewritten:
            rewritten = query

        log.info(
            "chat.query_rewrite",
            original=query,
            rewritten=rewritten,
            changed=rewritten != query,
            latency_ms=latency_ms,
        )
        return rewritten, latency_ms

    except Exception:
        latency_ms = int((time.monotonic() - t0) * 1000)
        log.warning("chat.query_rewrite_failed", query=query, latency_ms=latency_ms, exc_info=True)
        return query, latency_ms

if __name__ == "__main__":
    query = "If I want to focus on those to help with that, how can I actually start learning them without spending a fortune?"
    history = [
        {
            "role": "user",
            "content": "Hey, I’ve been thinking lately—what’s the actual secret to getting rich? Is it just luck, or is there a trick to it?"
        },
        {
            "role": "assistant",
            "content": "Honestly, I think the 'secret' is usually way less exciting than people hope! Most people who build wealth over time focus on things like consistent saving, learning high-value skills, and playing the long game rather than looking for a quick win."
        },
        {
            "role": "user",
            "content": "That sounds like a lot of work. Isn't there some kind of shortcut or a side hustle that just takes off overnight?"
        },
        {
            "role": "assistant",
            "content": "It’s definitely a grind! While you hear stories about overnight successes, they're pretty rare. Most of the time, those 'overnight' stories are actually the result of years of trial and error. It’s usually about finding a problem people have and solving it better than anyone else."
        }
    ]
    output = rewrite_query(query, history)
    print(output)
