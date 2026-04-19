"""Exemplar ingestion and augmentation for the intent classifier.

Usage:
    # Seed from examples.json
    python -m services.intent_service.intent_ingestion

    # Or import and call programmatically:
    from services.intent_service.intent_ingestion import seed_exemplars, add_exemplars
    seed_exemplars()
    add_exemplars([
        {"text": "what notes did I make in February?", "intent": "temporal"},
    ])
"""

from __future__ import annotations

import json
import os
import re

import structlog

from core.config import LLM_API_BASE
from pipeline.llm import llm_call
from services.intent_service.intent import IntentStore, VALID_INTENTS

log = structlog.get_logger()

_EXAMPLES_PATH = os.path.join(os.path.dirname(__file__), "examples.json")

_AUGMENTATION_PROMPT = """\
A personal notes app classifies user queries by intent.
The intent "{intent}" covers queries like: "{example}"

Write 5 realistic queries a real person would actually type into this app \
that clearly belong to the same intent.

Critical rules:
- Output ONLY the raw query text, exactly as a user would type it.
- NO labels, prefixes, tags, or annotations (no "Formal:", "Casual:", \
  "Terse:", "Fragment:", "(verbose)", numbering, etc.).
- NO quotation marks around the query.
- Each query must be a natural, standalone sentence or phrase.
- Vary vocabulary and sentence structure across the 5 queries.
- Every query must unambiguously belong to intent "{intent}".

Output exactly 5 lines, one query per line, nothing else."""

_AUGMENTATION_MODEL = "mistral-7b"

# Patterns that indicate leaked prompt artifacts rather than real queries
_NOISE_RE = re.compile(
    r"^\s*[\(\[]*\s*"
    r"(?:formal|casual|terse|verbose|fragment|variation|example|query|paraphrase)"
    r"\s*[\)\]:]*\s*",
    re.IGNORECASE,
)


def _clean_paraphrase(line: str) -> str | None:
    """Strip numbering, quotes, and prompt artifacts. Returns None if junk."""
    s = line.strip()
    if not s:
        return None
    # strip leading numbering: "1.", "1)", "1 -", etc.
    s = re.sub(r"^\d+[\.\)\-]\s*", "", s)
    # strip wrapping quotes
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        s = s[1:-1].strip()
    # strip leaked labels like "(Casual)" or "Formal:"
    s = _NOISE_RE.sub("", s).strip()
    # reject if too short or still looks like a label
    if len(s) < 5 or s.endswith(":"):
        return None
    return s


def seed_exemplars(path: str | None = None) -> int:
    """Load examples.json and ingest all seed exemplars into Qdrant."""
    path = path or _EXAMPLES_PATH
    with open(path, "r") as f:
        exemplars: dict[str, list[str]] = json.load(f)

    store = IntentStore()
    try:
        count = store.ingest(exemplars, source="seed")
        log.info("seed.complete", count=count)
        return count
    finally:
        store.close()


def add_exemplars(
    new_examples: list[dict],
    source: str = "production_log",
) -> int:
    """Ingest ad-hoc exemplars collected from logs or manual curation.

    Each item must have ``text`` and ``intent`` keys.
    """
    grouped: dict[str, list[str]] = {}
    for ex in new_examples:
        intent = ex["intent"]
        if intent not in VALID_INTENTS:
            log.warning("add_exemplars.unknown_intent", intent=intent)
            continue
        grouped.setdefault(intent, []).append(ex["text"])

    store = IntentStore()
    try:
        count = store.ingest(grouped, source=source)
        log.info("add_exemplars.complete", count=count)
        return count
    finally:
        store.close()


def augment_exemplars(path: str | None = None) -> int:
    """Use LLM to generate paraphrases of each seed example and ingest them."""
    path = path or _EXAMPLES_PATH
    with open(path, "r") as f:
        exemplars: dict[str, list[str]] = json.load(f)

    augmented: dict[str, list[str]] = {}
    for intent, examples in exemplars.items():
        if intent not in VALID_INTENTS:
            continue
        for example in examples:
            prompt = _AUGMENTATION_PROMPT.format(
                intent=intent, example=example,
            )
            try:
                body = llm_call(
                    {
                        "model": _AUGMENTATION_MODEL,
                        "messages": [
                            {"role": "user", "content": prompt},
                        ],
                        "max_tokens": 300,
                        "temperature": 0.7,
                    },
                    base_url=LLM_API_BASE,
                    timeout=60.0,
                )
                raw = body["choices"][0]["message"]["content"].strip()
                cleaned = []
                for line in raw.splitlines():
                    q = _clean_paraphrase(line)
                    if q:
                        cleaned.append(q)
                augmented.setdefault(intent, []).extend(cleaned[:5])
                log.info(
                    "augment.generated",
                    intent=intent,
                    seed=example,
                    count=len(cleaned[:5]),
                )
            except Exception:
                log.warning(
                    "augment.failed",
                    intent=intent,
                    seed=example,
                    exc_info=True,
                )

    if not augmented:
        return 0

    store = IntentStore()
    try:
        count = store.ingest(augmented, source="augmented")
        log.info("augment.complete", count=count)
        return count
    finally:
        store.close()


if __name__ == "__main__":
    from core.settings import init_llama_index_settings
    init_llama_index_settings()

    print("=== Seeding exemplars ===")
    n = seed_exemplars()
    print(f"Ingested {n} seed exemplars")

    print("\n=== Augmenting with LLM paraphrases ===")
    n = augment_exemplars()
    print(f"Ingested {n} augmented exemplars")
