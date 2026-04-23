"""Regex-based keyword extraction for keyword_count and presence_check queries.

Extracts the target keyword/phrase from the raw query text without an LLM.
Used as a fallback when the classifier detects the intent but doesn't fill
``plan.search_term`` or ``plan.slots["topic"]``.
"""

from __future__ import annotations

import re


class KeywordExtractor:
    """Pull the target keyword/phrase from a query using ordered regex patterns."""

    # Base / past-participle verb forms shared across tiers.
    # Order matters: longer phrasal verbs must precede shorter prefixes
    # (e.g. "note down" before "note") so regex alternation picks them first.
    _V = (
        r"mention(?:ed)?|writ(?:ten|e) about|write about|write|reference[d]?|"
        r"talk(?:ed)? about|brought up|bring up|discuss(?:ed)?|"
        r"use[d]?|say|said|cover(?:ed)?|"
        r"touch(?:ed)? on|jot(?:ted)? down|note[d]? down|note[d]?"
    )

    PATTERNS = [
        # ══════════════════════════════════════════════
        # TIER 1: Quoted terms
        # ══════════════════════════════════════════════
        r'"([^"]+)"',
        r'\u201c(.+?)\u201d',
        r'\u2018(.+?)\u2019',
        r"'(.+)'",

        # ══════════════════════════════════════════════
        # TIER 2: Explicit count patterns
        # ══════════════════════════════════════════════

        # "have X in them/it/my notes"
        r"how many\s+(?:notes?|entries?)\s+have\s+(.+?)\s+in\s+(?:them|it|my\s+notes?)[\s?.!]*$",

        # "does X appear/come up/show up in my notes"
        r"how many\s+times?\s+does\s+(.+?)\s+(?:appear|come up|show up|pop up|turn up|occur)(?:\s+.*)?[\s?.!]*$",
        r"does\s+(.+?)\s+(?:appear|come up|show up|pop up|turn up|occur)(?:\s+.*)?[\s?.!]*$",

        # "how many times did/do/have I mention/write/... X" — must precede the
        # generic "how many notes mention X" pattern so "have I" doesn't get
        # consumed by "have" in that verb list.
        r"how many\s+times?\s+(?:did I|do I|does?|have I|has it|was)\s+"
        rf"(?:{_V})\s+(.+?)[\s?.!]*$",

        # "how often/frequently/regularly did I ... X"
        r"how (?:often|frequently|regularly)\s+(?:did I|do I|have I|was I)\s+"
        rf"(?:{_V})\s+(.+?)[\s?.!]*$",

        # "how many notes mention/talk about/... X"
        r"how many\s+(?:notes?|times?|entries?|journal entries?)\s+"
        r"(?:mention|reference|referencing|talk about|discuss|bring up|contain|include|have|are about|"
        r"are related to|are on|cover|address|touch on)\s+(.+?)[\s?.!]*$",

        # "count notes/entries ... mentioning/referencing X"
        r"count\s+(?:notes?|entries?|times?|journal entries?)\s+"
        r"(?:that\s+)?(?:mention|mentioning|reference|referencing|about|with|containing|"
        r"related to|discussing|on|regarding)\s+(.+?)[\s?.!]*$",

        r"count\s+(?:occurrences?|instances?|uses?|mentions?)\s+of\s+(.+?)(?:\s+(?:across|in|within|throughout)\s+.*)?[\s?.!]*$",

        r"number of\s+(?:notes?|entries?|times?|journal entries?)\s+"
        r"(?:that\s+)?(?:mention|mentioning|reference|referencing|about|on|with|discussing|"
        r"containing|related to|regarding|covering|touching on)\s+(.+?)[\s?.!]*$",

        # ══════════════════════════════════════════════
        # TIER 3: Quantity-implied patterns
        # ══════════════════════════════════════════════

        r"(?:do I have|are there|have I got)\s+"
        r"(?:a lot of|many|lots of|several|much|numerous|a ton of|loads of|plenty of|a bunch of|"
        r"quite a few|any number of)\s+"
        r"(?:notes?|entries?|journal entries?)\s+"
        r"(?:about|on|mentioning|regarding|related to|discussing|covering|that mention|on the topic of)\s+"
        r"(.+?)[\s?.!]*$",

        # "do my notes mention X frequently?"
        r"do\s+(?:my\s+)?(?:notes?|entries?|journal)\s+"
        r"(?:mention|reference|discuss|contain|include|talk about|cover)\s+"
        r"(.+?)(?:\s+(?:a lot|often|frequently|much|regularly|a ton|all the time))?(?:\s+.*)?[\s?.!]*$",

        # "do I mention X a lot/often/..."
        r"do I\s+(?:mention|write about|reference|talk about|bring up|discuss|"
        r"note|jot down|touch on|cover)\s+"
        r"(.+?)\s+(?:a lot|much|often|frequently|regularly|a ton|all the time|"
        r"that often|that much|quite a bit|so much)(?:\s+.*)?[\s?.!]*$",

        r"do I\s+(?:mention|write about|reference|talk about|bring up|discuss)\s+"
        r"(.+?)\s+(?:frequently|regularly|often|repeatedly|constantly)[\s?.!]*$",

        # "is X a frequent topic / mentioned a lot / something I write about"
        r"is\s+(.+?)\s+(?:a frequent|a common|a recurring|a regular|a popular|"
        r"mentioned a lot|something I (?:write|mention|talk)\s*(?:about\s+)?(?:often|a lot|frequently)|"
        r"a topic I (?:cover|discuss|write about) (?:often|a lot|frequently))",

        r"is\s+(.+?)\s+(?:mentioned|referenced|discussed|covered|brought up)\s+"
        r"(?:a lot|often|frequently|regularly|much|more often)(?:\s+.*)?[\s?.!]*$",

        # ══════════════════════════════════════════════
        # TIER 4: Indirect / conversational
        # ══════════════════════════════════════════════

        # "did/do/have I (ever) mentioned/discussed/... X"
        rf"(?:did|do|have)\s+I\s+(?:ever\s+)?(?:{_V})\s+(.+?)[\s?.!]*$",

        r"(?:is there|are there)\s+(?:anything|something|stuff|notes?|entries?|much|a lot)\s+"
        r"(?:about|on|regarding|mentioning|related to|concerning|to do with)\s+"
        r"(.+?)(?:\s+(?:in|within|across|throughout)\s+.*)?[\s?.!]*$",

        r"(?:check|see|find out|verify|confirm|look if)\s+"
        r"(?:if|whether)\s+I\s+(?:wrote|write|mentioned|have|had|ever wrote|ever mentioned)\s+"
        r"(?:about\s+|anything about\s+)?(.+?)[\s?.!]*$",

        # "I'm curious / I wonder / wondering how many/often ... X"
        r"(?:I'm curious|I wonder|just wondering|curious|wondering)\s+"
        r"(?:how many|how often|how frequently|if)\s+.*?"
        r"(?:mention|write about|reference|discuss)\s+(.+?)[\s?.!]*$",

        # "seems like I mention X often" / "I feel like I write about X a lot"
        r"(?:seems like|I feel like|I think|it seems)\s+I\s+"
        rf"(?:{_V})\s+(.+?)[\s?.!]*$",

        # "would you say I write about X a lot?"
        r"(?:would you say|could you check|can you check)\s+I\s+"
        rf"(?:{_V})\s+(.+?)[\s?.!]*$",

        # ══════════════════════════════════════════════
        # TIER 5: Structural variants
        # ══════════════════════════════════════════════

        r"how many\s+(?:of my\s+)?(?:notes?|entries?)\s+"
        r"(?:say something about|say anything about|talk about|mention|contain|have something about)\s+"
        r"(.+?)[\s?.!]*$",

        r"(?:notes?|entries?)\s+(?:mentioning|about|referencing|discussing|containing|on)\s+"
        r"(.+?)\s*[,\u2014\u2013-]\s*how many[\s?.!]*$",

        r"^(.+?)\s*[\u2014\u2013-]+\s*how many\s+(?:notes?|entries?|times?|mentions?)[\s?.!]*$",

        r"(?:tell me|let me know|can you tell me|show me)\s+"
        r"how many\s+(?:notes?|entries?|times?)\s+"
        r"(?:mention|reference|talk about|discuss|contain|are about)\s+(.+?)[\s?.!]*$",

        # ══════════════════════════════════════════════
        # TIER 6: Terse / inverted
        # ══════════════════════════════════════════════

        r"^count\s+(.+?)[\s?.!]*$",
        r"^(.+?)\s+count[\s?.!]*$",

        # ══════════════════════════════════════════════
        # TIER 7: Fallback
        # ══════════════════════════════════════════════

        r"how many\s+.*?(?:about|mention(?:ing)?|on|with|for|regarding|related to|containing|discussing)\s+(.+?)[\s?.!]*$",

        r"(?:about|mention(?:ing)?|reference|regarding|on the topic of|related to|concerning)\s+(.+?)[\s?.!]*$",
    ]

    MULTI_PATTERNS = [
        # "do I mention X more than Y?"
        r"(?:do I|did I|have I)\s+(?:mention|write about|reference|discuss|talk about)\s+"
        r"(.+?)\s+(?:more than|more often than|less than|less often than|or)\s+(.+?)[\s?.!]*$",

        # "is X mentioned more often than Y?"
        r"is\s+(.+?)\s+(?:mentioned|referenced|discussed|written about)\s+"
        r"(?:more than|more often than|less than|less often than)\s+(.+?)[\s?.!]*$",

        # "how many more notes mention X than Y?"
        r"how many\s+(?:more\s+)?(?:notes?|times?|entries?)\s+"
        r"(?:mention|reference|discuss|talk about)\s+"
        r"(.+?)\s+(?:than|vs\.?|versus|compared to|or)\s+(.+?)[\s?.!]*$",

        # "X or Y, which do I mention more?"
        r"^(.+?)\s+(?:or|vs\.?|versus)\s+(.+?)[,\s]+(?:which|what)\s+(?:do I|did I)\s+(?:mention|write about)\s+more[\s?.!]*$",

        # "compare mentions of X and Y"
        r"(?:compare|contrast)\s+(?:mentions?|occurrences?|references?)\s+of\s+"
        r"(.+?)\s+(?:and|with|vs\.?|versus|to)\s+(.+?)[\s?.!]*$",

        # "X vs Y count" / "count X and Y"
        r"(?:count|compare)\s+(.+?)\s+(?:and|vs\.?|versus)\s+(.+?)[\s?.!]*$",

        # "do I write more about X or Y?"
        r"do I\s+(?:write|mention|talk)\s+more about\s+(.+?)\s+or\s+(.+?)[\s?.!]*$",

        # "between X and Y, which comes up more?"
        r"between\s+(.+?)\s+and\s+(.+?)[,\s]+(?:which|what)\s+(?:comes up|appears|is mentioned)\s+more[\s?.!]*$",
    ]

    _STOPWORDS = frozenset({
        "the", "a", "an", "some", "any", "this", "that", "these", "those",
        "my", "i", "me", "mine", "we", "our", "you", "your",
        "in", "on", "about", "of", "for", "to", "at", "from", "with",
        "into", "within", "across", "throughout", "between",
        "and", "or", "but", "nor",
        "is", "are", "was", "were", "be", "been", "being",
        "do", "does", "did", "have", "has", "had",
        "entries", "entry", "journal",
        "folder", "folders", "tag", "tags",
        "word", "phrase", "term", "topic",
        "something", "anything", "stuff", "things",
        "just", "also", "really", "very", "quite", "pretty",
        "most", "least",
    })

    # Trailing noise phrases stripped after extraction (order: longest first)
    _TRAILING_NOISE = re.compile(
        r"(?:\s+(?:"
        r"more often than\b.*|more than\b.*|than\b.*|"
        r"a lot\b.*|all the time\b.*|quite a bit\b.*|"
        r"often\b.*|frequently\b.*|regularly\b.*|"
        r"much\b.*|a ton\b.*|so much\b.*|"
        r"that often\b.*|that much\b.*|"
        r"constantly\b.*|repeatedly\b.*"
        r"))$",
        re.IGNORECASE,
    )

    _STRIP_CHARS = "?,;:'\"\u201c\u201d\u2018\u2019\u2014 \t\n"

    @classmethod
    def extract(cls, query: str) -> str | None:
        q = query.strip()

        for pattern in cls.PATTERNS:
            match = re.search(pattern, q, re.IGNORECASE)
            if match:
                keyword = cls._clean(match.group(1))
                if keyword:
                    return keyword

        return None

    @classmethod
    def extract_multiple(cls, query: str) -> list[str]:
        """
        Try multi-keyword extraction first.
        Falls back to single extraction wrapped in a list.
        """
        q = query.strip()

        # Try multi-keyword patterns
        for pattern in cls.MULTI_PATTERNS:
            match = re.search(pattern, q, re.IGNORECASE)
            if match:
                terms = []
                for group in match.groups():
                    cleaned = cls._clean(group)
                    if cleaned:
                        terms.append(cleaned)
                if len(terms) >= 2:
                    return terms

        # Fall back to single keyword
        single = cls.extract(q)
        if single:
            return [single]

        return []

    @classmethod
    def _clean(cls, raw: str) -> str | None:
        if not raw:
            return None

        cleaned = raw.strip(cls._STRIP_CHARS)

        # Strip emoji
        cleaned = re.sub(
            r'[\U0001F300-\U0001F9FF\U00002702-\U000027B0\U0000FE00-\U0000FE0F\U0000200D]',
            '', cleaned,
        ).strip()

        # Strip leading ellipsis / dots (but not a lone leading dot like ".NET")
        cleaned = re.sub(r'^\.{2,}\s*', '', cleaned).strip()

        # Strip trailing dots / ellipsis / exclamation
        cleaned = re.sub(r'[.!]+$', '', cleaned).strip()

        # Strip trailing noise phrases ("a lot", "often", "more than X", etc.)
        cleaned = cls._TRAILING_NOISE.sub('', cleaned).strip()

        # Strip trailing comma + clause (", how many times?", ", is that true?")
        cleaned = re.sub(r',\s+.*$', '', cleaned).strip()

        words = cleaned.split()
        while words and words[0].lower() in cls._STOPWORDS:
            words.pop(0)
        while words and words[-1].lower() in cls._STOPWORDS:
            words.pop()

        cleaned = " ".join(words).strip()
        cleaned = cleaned.strip(cls._STRIP_CHARS)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()

        if not cleaned or len(cleaned) > 60 or len(cleaned) <= 1:
            return None

        # Context words valid inside phrases ("meeting notes") but noise standalone
        if cleaned.lower() in {"notes", "note", "entries", "entry", "journal"}:
            return None

        return cleaned
