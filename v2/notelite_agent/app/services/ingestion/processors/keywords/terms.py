import re


NOISE_NOUNS = {
    "thing", "things", "stuff", "bit", "bits", "piece", "pieces",
    "way", "ways", "kind", "kinds", "sort", "sorts", "lot", "lots",
    "something", "anything", "everything", "nothing",
    "time", "times", "day", "days", "night", "nights",
    "today", "tonight", "yesterday", "tomorrow",
    "year", "years", "week", "weeks", "month", "months",
    "opening", "closing", "beginning", "ending", "start", "finish",
    "middle", "center", "top", "bottom", "side", "front", "back",
    "part", "parts", "section", "chapter", "rest", "half",
    "end", "ends", "area", "areas", "place", "places",
    "activity", "activities", "conversation", "conversations",
    "introduction", "conclusion", "discussion", "discussions",
    "case", "example", "instance", "matter", "issue",
    "question", "answer", "result", "reason", "idea", "fact",
    "number", "amount", "level", "point", "points",
    "people", "person", "man", "woman",
    "general", "main", "basic", "simple", "common", "typical", "life",
    "process", "factor",
}

VAGUE_TRAIL = {
    "thing", "things", "stuff", "bit", "bits", "piece", "pieces",
    "way", "ways", "kind", "kinds", "sort", "sorts", "lot", "lots",
    "time", "times", "day", "days", "night", "nights",
    "today", "tonight", "yesterday", "tomorrow",
    "activity", "activities", "conversation", "conversations",
    "discussion", "discussions", "introduction", "conclusion",
    "people", "person",
}

FUNC_WORDS = {
    "a", "an", "the", "and", "or", "but", "of", "in", "on", "at",
    "to", "for", "by", "with", "from", "as", "is", "are", "was", "were",
    "be", "been", "being", "it", "its", "this", "that", "these", "those",
    "all", "some", "any", "many", "few", "other", "another",
    "when", "where", "while", "if", "then", "also", "just",
    "my", "our", "your", "his", "her", "their",
    "very", "so", "too", "more", "most", "not", "no",
    "about", "between", "into", "through", "during", "before", "after",
    "above", "below", "up", "down", "out", "off", "over", "under",
    "give", "gave", "get", "got", "make", "made", "take", "took",
    "say", "said", "see", "saw", "let", "put", "go", "went", "come", "came",
    "look", "looked", "find", "found", "know", "knew", "think", "thought",
    "want", "wanted", "need", "needed", "use", "used", "try", "tried",
    "keep", "kept", "seem", "seemed", "show", "showed", "shown",
    "tell", "told", "ask", "asked", "turn", "turned", "help", "helped",
    "spend", "spent", "handle", "handled", "deal", "dealing",
    "miss", "missed", "conclude", "concluded",
    "consider", "considered", "provide", "provided",
    "notice", "noticed", "realize", "realized",
    "mention", "mentioned", "talk", "talked", "talking",
}

LEAD_STRIP = FUNC_WORDS | VAGUE_TRAIL
TRAIL_STRIP = FUNC_WORDS | VAGUE_TRAIL


def clean_term(term: str) -> str | None:
    term = re.sub(r"\s+", " ", term).strip()
    if len(term) < 3:
        return None

    words = term.split()
    while len(words) > 1 and words[0] in LEAD_STRIP:
        words.pop(0)
    while len(words) > 1 and words[-1] in TRAIL_STRIP:
        words.pop()

    if len(words) > 4:
        words = words[:4]

    term = " ".join(words)
    if not term or len(term) < 3:
        return None
    if len(words) == 1 and (term in NOISE_NOUNS or term in LEAD_STRIP):
        return None

    return term


def stem(word: str) -> str:
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if len(word) > 4:
        for suffix in ("ches", "shes", "ses", "xes", "zes"):
            if word.endswith(suffix):
                return word[:-2]
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


def split_tokens(phrase: str) -> set[str]:
    tokens = set()
    for word in phrase.split():
        tokens.add(stem(word))
        if "-" in word:
            tokens.update(stem(part) for part in word.split("-") if part)
    return tokens


def is_subphrase(a: str, b: str) -> bool:
    return split_tokens(a).issubset(split_tokens(b))


def prune_keywords(keywords: list[str]) -> list[str]:
    selected = []
    for keyword in keywords:
        keep = True
        to_remove = []

        for existing in selected:
            if is_subphrase(keyword, existing):
                keep = False
                break
            if is_subphrase(existing, keyword):
                to_remove.append(existing)

        if keep:
            for existing in to_remove:
                selected.remove(existing)
            selected.append(keyword)

    return selected
