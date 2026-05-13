import re

_REGEX_RULES: list[tuple[re.Pattern, str, int | None]] = [
    # corpus_stats
    (re.compile(
        r"how\s+many\s+(?:notes?|folders?)\s+(?:do\s+)?I\s+have", re.I,
    ), "corpus_stats", None),
    (re.compile(
        r"(?:total|count)\s+(?:of\s+)?(?:all\s+)?(?:notes?|folders?)", re.I,
    ), "corpus_stats", None),
    (re.compile(
        r"(?:largest|biggest|smallest|longest|shortest)\s+note", re.I,
    ), "corpus_stats", None),
    (re.compile(r"(?:empty|unused)\s+folders?", re.I), "corpus_stats", None),

    # conversation_meta
    (re.compile(
        r"(?:repeat|say)\s+(?:that|last|your\s+(?:last|previous))", re.I,
    ), "conversation_meta", None),
    (re.compile(
        r"what\s+(?:did|were)\s+(?:i|we)\s+(?:just\s+)?(?:ask|talk)", re.I,
    ), "conversation_meta", None),
    (re.compile(
        r"^\s*(?:thanks|thank\s+you|bye|goodbye|that'?s\s+all|never\s*mind)\s*[.!]?\s*$",
        re.I,
    ), "conversation_meta", None),

    # locate_note (singular specific item)
    (re.compile(
        r"(?:find|locate)\s+(?:the|my|that)\s+note\b", re.I,
    ), "locate_note", None),
    (re.compile(
        r"where(?:'s|\s+is|\s+did\s+I\s+(?:put|save))\s+(?:the|my|that)\s+",
        re.I,
    ), "locate_note", None),
    (re.compile(
        r"show\s+me\s+(?:the\s+one|that\s+note|the\s+note)\b", re.I,
    ), "locate_note", None),
    (re.compile(
        r"which\s+(?:note|file|folder)\s+(?:has|contains|mentions)\b", re.I,
    ), "locate_note", None),

    # presence_check (yes/no existence)
    (re.compile(
        r"(?:did|have)\s+I\s+ever\s+(?:writ|not|mention|jot|save)", re.I,
    ), "presence_check", None),
    (re.compile(
        r"do\s+I\s+have\s+(?:any(?:thing)?|something)\s+(?:about|on|regarding)\b",
        re.I,
    ), "presence_check", None),
    (re.compile(
        r"is\s+there\s+(?:a\s+)?note\s+(?:about|on|for|where)\b", re.I,
    ), "presence_check", None),

    # keyword_count
    (re.compile(
        r"how\s+many\s+times.*?"
        r"(?:say|said|mention(?:ed)?|wrote|write|use[ds]?|written|type[ds]?)"
        r"\s+['\"]?(.+?)['\"]?\s*\??$",
        re.I,
    ), "keyword_count", 1),
    (re.compile(
        r"(?:count|total\s+number\s+of)\s+.*?['\"](.+?)['\"]", re.I,
    ), "keyword_count", 1),

    # temporal
    (re.compile(
        r"when\s+did\s+(?:i|we)\s+.*?"
        r"(?:say|said|mention|write|wrote|add|added|note|create)",
        re.I,
    ), "temporal", None),

    # list_notes
    (re.compile(
        r"(?:list\s+all|show\s+(?:me\s+)?all|what\s+are\s+all)\b", re.I,
    ), "list_notes", None),
]