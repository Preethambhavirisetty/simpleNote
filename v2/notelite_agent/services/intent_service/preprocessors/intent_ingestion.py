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

_CONFUSABLE_INTENTS = {
    "semantic":         ["list_notes", "locate_note"],
    "locate_note":      ["list_notes", "semantic"],
    "list_notes":       ["semantic", "locate_note"],
    "keyword_count":    ["presence_check", "corpus_stats"],
    "temporal":         ["semantic", "list_notes"],
    "presence_check":   ["keyword_count", "semantic"],
    "compare_notes":    ["keyword_count", "semantic"],
    "corpus_stats":     ["keyword_count", "locate_note"],
    "conversation_meta":["locate_note", "semantic"],
    "clarify_intent":   ["semantic", "list_notes"],
}


def build_confusable_block(intent: str, all_examples: dict) -> str:
    confusable_intents = _CONFUSABLE_INTENTS.get(intent, [])
    lines = []
    for conf_intent in confusable_intents:
        examples = all_examples.get(conf_intent, [])[:3]  # just 3 examples
        for ex in examples:
            lines.append(f"- \"{ex}\" → this is {conf_intent}, NOT {intent}")
    return "\n".join(lines)

_INTENT_DESCRIPTIONS = {
    "semantic": "User wants to understand, summarize, or recall the CONTENT of their notes. "
        "Key signals: 'summarize', 'what did I write about', 'what do my notes say', "
        "'tell me about', 'what are my thoughts on', 'recap', 'gist of'. "
        "NOT list_notes (which just enumerates titles), NOT locate_note (which finds a specific one).",
    "locate_note": "User wants to find ONE specific note or the folder/location where it lives. "
        "Key signals: 'find the note', 'which note has', 'where is the note', 'show me the one about', "
        "'that note about', 'which folder has'. Singular 'note'/'one', demonstratives 'that'/'the'. "
        "NOT list_notes (which wants ALL notes on a topic).",
    "list_notes": "User wants to see ALL notes matching a topic, tag, or folder. "
        "Key signals: 'all my notes on', 'list notes about', 'everything tagged', "
        "'show me every note', 'pull up all', plural 'notes'. Bare topic+plural like 'travel notes'. "
        "NOT semantic (which wants content understanding), NOT locate_note (which wants one specific note).",
    "keyword_count": "User wants a COUNT or frequency of how often a keyword/topic appears. "
        "Key signals: 'how many notes mention', 'count notes that', 'how often', 'how frequently', "
        "'number of notes mentioning'. Wants a NUMBER, not a list. "
        "NOT presence_check (which asks yes/no existence), NOT list_notes (which wants the notes themselves).",
    "temporal": "User wants notes filtered by TIME or wants to know WHEN something was written. "
        "Key signals: 'last week', 'from March', 'yesterday', 'most recent', 'when did I write', "
        "'this month', 'oldest'. Time is the PRIMARY filter. "
        "NOT semantic (even if a topic is mentioned, time is the main axis).",
    "presence_check": "User wants a YES/NO answer about whether a note exists on a topic. "
        "Key signals: 'did I ever write about', 'do I have anything on', 'is there a note about', "
        "'have I mentioned', 'any note about'. Existence check, not retrieval. "
        "NOT keyword_count (which wants how many), NOT locate_note (which wants to find it).",
    "compare_notes": "User wants to COMPARE, CONTRAST, or find DIFFERENCES between two or more notes/topics. "
        "Key signals: 'compare', 'contrast', 'differences between', 'how do X and Y differ', "
        "'is there more about X or Y', 'what changed between', 'consistent'. "
        "NOT keyword_count (which counts one keyword), NOT presence_check.",
    "corpus_stats": "User wants METADATA or STATISTICS about their entire note collection. "
        "Key signals: 'how many notes do I have', 'total word count', 'largest/smallest/longest note', "
        "'how many folders', 'average length', 'breakdown per folder'. About the COLLECTION, not content. "
        "NOT keyword_count (which counts mentions of a specific word).",
    "conversation_meta": "User is referring to THIS CHAT CONVERSATION, not their notes. OR saying goodbye. "
        "Key signals: 'what did I just ask you', 'repeat your last answer', 'what were we talking about', "
        "'you mentioned earlier', 'thanks that's all', 'bye', 'I'm done'. "
        "NOT semantic (which asks about note content), NOT locate_note.",
    "clarify_intent": "Query is AMBIGUOUS, contains MULTIPLE intents combined, or requests an UNSUPPORTED ACTION. "
        "Key signals: vague single words ('notes', 'stuff'), multi-intent ('list my notes and also count...'), "
        "unsupported actions ('delete', 'edit', 'export', 'share', 'create'). "
        "NOT any specific intent — this is the catch-all for unclear queries.",
}

_AUGMENTATION_PROMPT = """\
You are generating training data for an intent classifier in a personal notes app.

TARGET INTENT: "{intent}"
DESCRIPTION: {intent_description}

SEED EXAMPLE: "{example}"

AVOID generating queries like these (they belong to OTHER intents):
{confusable_examples}

Generate exactly 2 NEW queries that clearly belong to intent "{intent}".

Requirements:
1. Each query must be something a real person would actually type — vary between \
formal, casual, terse, and conversational styles.
2. Use DIFFERENT vocabulary, sentence structures, and topics from the seed. \
Don't just swap one word — change the whole phrasing.
3. Each query must UNAMBIGUOUSLY belong to "{intent}" and NOT be confusable \
with any other intent. Think about what makes this intent distinct.
4. Include at least one SHORT query (2-5 words) and one LONGER natural query.
5. Do NOT include any labels, numbers, prefixes, quotes, or annotations.

Output exactly 2 lines, one raw query per line, nothing else."""

_AUGMENTATION_MODEL = "mistral-7b"

# Patterns that indicate leaked prompt artifacts rather than real queries
_NOISE_RE = re.compile(
    r"^\s*[\(\[]*\s*"
    r"(?:formal|casual|terse|verbose|fragment|variation|example|query|paraphrase|short|long|longer|natural)"
    r"\s*[\)\]:]*\s*",
    re.IGNORECASE,
)

_INTENT_LEAK_RE = re.compile(
    r"\b(?:intent|classify|classification|belongs?\s+to|category)\b",
    re.IGNORECASE,
)

def _clean_paraphrase(line: str) -> str | None:
    """Strip numbering, quotes, and prompt artifacts. Returns None if junk."""
    s = line.strip()
    if not s:
        return None
    # skip lines that look like instructions or commentary
    if s.startswith("Here") or s.startswith("Sure") or s.startswith("Note:"):
        return None
    # strip leading numbering: "1.", "1)", "1 -", "- ", "* "
    s = re.sub(r"^\d+[\.\)\-]\s*", "", s)
    s = re.sub(r"^[-*]\s+", "", s)
    # strip wrapping quotes
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        s = s[1:-1].strip()
    # strip leaked labels like "(Casual)" or "Formal:"
    s = _NOISE_RE.sub("", s).strip()
    # reject if too short, still looks like a label, or leaks intent terminology
    if len(s) < 5 or s.endswith(":") or _INTENT_LEAK_RE.search(s):
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
        confusable_block = build_confusable_block(intent, exemplars)
        for example in examples:
            prompt = _AUGMENTATION_PROMPT.format(
                intent=intent,
                example=example,
                intent_description=_INTENT_DESCRIPTIONS.get(intent, ""),
                confusable_examples=confusable_block or "(none)",
            )
            try:
                body = llm_call(
                    {
                        "model": _AUGMENTATION_MODEL,
                        "messages": [
                            {"role": "user", "content": prompt},
                        ],
                        "max_tokens": 200, # 3 ques x ~15 words x ~2 token/word = 90, still more head room
                        "temperature": 0.9,
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
                augmented.setdefault(intent, []).extend(cleaned[:2])
                log.info(
                    "augment.generated",
                    intent=intent,
                    seed=example,
                    count=len(cleaned[:2]),
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
    try:
        import multiprocess.resource_tracker as _rt
        _rt.ResourceTracker.__del__ = lambda self: None
    except Exception:
        pass

    from core.settings import init_llama_index_settings
    init_llama_index_settings()

    print("=== Seeding exemplars ===")
    n = seed_exemplars()
    print(f"Ingested {n} seed exemplars")

    print("\n=== Augmenting with LLM paraphrases ===")
    n = augment_exemplars()
    print(f"Ingested {n} augmented exemplars")
