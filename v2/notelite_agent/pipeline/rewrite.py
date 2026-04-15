"""Query rewriting for multi-turn conversations.

Rewrites vague follow-up queries (e.g. "what about the second one?") into
self-contained queries (e.g. "what is the second item in my grocery list?")
so vector search can retrieve relevant chunks.
"""

from __future__ import annotations

import time

import httpx
import structlog

from core.config import CHAT_LLM_API_BASE, LLM_API_KEY

log = structlog.get_logger()

_REWRITE_SYSTEM_PROMPT = """\
Rewrite the user's latest question into a single, self-contained question. \
Do NOT answer it.

Rules:
- The output must be a question (ending with ?), never a statement or answer.
- Replace pronouns (it, that, they, etc.) with the specific nouns from the conversation.
- Keep it concise — one sentence.
- If the question is already self-contained, return it exactly as-is.

Example:
History: User asked about grocery list. Assistant said milk, eggs, bread.
Latest: "did I add anything else?"
Output: Did I add anything else to my grocery list besides milk, eggs, and bread?"""

_MAX_TOKENS = 64
_TIMEOUT = 30.0


def rewrite_query(query: str, history: list[dict]) -> tuple[str, int]:
    """Rewrite a follow-up query using conversation history.

    Returns (rewritten_query, latency_ms).
    Falls back to the original query on any error.
    """
    history_block = "\n".join(
        f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
        for m in history[-6:]  # last 3 turns is enough context for rewriting
    )

    t0 = time.monotonic()
    try:
        resp = httpx.post(
            f"{CHAT_LLM_API_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {LLM_API_KEY}"},
            json={
                "model": "llama3.1",
                "messages": [
                    {"role": "system", "content": _REWRITE_SYSTEM_PROMPT},
                    {"role": "user", "content": f"History:\n{history_block}\n\nLatest question: {query}"},
                ],
                "max_tokens": _MAX_TOKENS,
                "temperature": 0.0,
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        rewritten = resp.json()["choices"][0]["message"]["content"].strip()
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
