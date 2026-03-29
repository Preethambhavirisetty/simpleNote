import re
import logging

log = logging.getLogger(__name__)

_spacy_nlp = None
_yake_extractor = None

# Blocked as STANDALONE single-word keywords only.
# Multi-word phrases containing these words survive (e.g., "test case" OK, "case" alone blocked).
_NOISE_NOUNS = {
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
    "process", "factor"
}

# Genuinely meaningless at BOTH edges of compounds — stripped from either side.
# Does NOT include words like "case", "main" that are meaningful in compounds.
_VAGUE_TRAIL = {
    "thing", "things", "stuff", "bit", "bits", "piece", "pieces",
    "way", "ways", "kind", "kinds", "sort", "sorts", "lot", "lots",
    "time", "times", "day", "days", "night", "nights",
    "today", "tonight", "yesterday", "tomorrow",
    "activity", "activities", "conversation", "conversations",
    "discussion", "discussions", "introduction", "conclusion",
    "people", "person",
}

# Function words + verbs + vague nouns — stripped from LEADING position.
# Adjectives like "main", "new", "specific" are NOT here so "main priority" survives.
_FUNC_WORDS = {
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

_LEAD_STRIP = _FUNC_WORDS | _VAGUE_TRAIL
_TRAIL_STRIP = _FUNC_WORDS | _VAGUE_TRAIL


# ── Model / extractor singletons ─────────────────────────────────────────

def _get_spacy_nlp():
    global _spacy_nlp
    if _spacy_nlp is None:
        try:
            import spacy
            _spacy_nlp = spacy.load("en_core_web_sm")
        except (ImportError, OSError):
            log.warning("spaCy model not available; falling back to YAKE-only keywords")
            _spacy_nlp = False
    return _spacy_nlp if _spacy_nlp is not False else None


def _get_yake_extractor():
    global _yake_extractor
    if _yake_extractor is None:
        import yake
        _yake_extractor = yake.KeywordExtractor(lan="en", n=3, top=20, dedupLim=0.7)
    return _yake_extractor


# ── POS validation ───────────────────────────────────────────────────────

def _build_noun_set(doc) -> set[str]:
    """Build a set of NOUN/PROPN lemmas from a spaCy doc."""
    nouns = set()
    for token in doc:
        if token.pos_ in ("NOUN", "PROPN") and not token.is_stop:
            nouns.add(token.lemma_.lower())
            nouns.add(token.text.lower())
    return nouns


def _has_noun(term: str, noun_set: set[str]) -> bool:
    """Check if at least one word in the term is a known noun from the doc."""
    for word in term.split():
        if word in noun_set:
            return True
        if '-' in word:
            for part in word.split('-'):
                if part and part in noun_set:
                    return True
    return False


def _refine_with_pos(term: str, noun_set: set[str]) -> str | None:
    """Strip non-noun edges from multi-word terms using POS info.

    Handles YAKE artifacts like 'process easy' → 'process'
    and 'specific cisco' → 'cisco'.
    """
    words = term.split()
    if len(words) <= 1:
        return term

    while len(words) > 1 and words[-1] not in noun_set:
        words.pop()

    while len(words) > 1 and words[0] not in noun_set:
        words.pop(0)

    term = ' '.join(words)
    if not term or len(term) < 3:
        return None
    if len(words) == 1 and term in _NOISE_NOUNS:
        return None
    return term


# ── Term cleaning ────────────────────────────────────────────────────────

def _clean_term(term: str) -> str | None:
    """Normalize whitespace, strip noisy edges, reject junk."""
    term = re.sub(r'\s+', ' ', term).lower().strip()

    if len(term) < 3:
        return None

    words = term.split()

    # strip leading function words / verbs only (keep adjective modifiers)
    while len(words) > 1 and words[0] in _LEAD_STRIP:
        words.pop(0)

    # strip trailing function words + vague nouns
    while len(words) > 1 and words[-1] in _TRAIL_STRIP:
        words.pop()

    if len(words) > 4:
        words = words[:4]

    term = ' '.join(words)

    if not term or len(term) < 3:
        return None

    if len(words) == 1 and (term in _NOISE_NOUNS or term in _LEAD_STRIP):
        return None

    return term


# ── Subphrase / pruning utilities ────────────────────────────────────────

def _split_tokens(phrase: str) -> set[str]:
    tokens = set()
    for word in phrase.split():
        tokens.add(word)
        if '-' in word:
            tokens.update(part for part in word.split('-') if part)
    return tokens


def _is_subphrase(a: str, b: str) -> bool:
    return _split_tokens(a).issubset(_split_tokens(b))


def prune_keywords(keywords: list[str]) -> list[str]:
    if not keywords:
        return []

    selected: list[str] = []
    for kw in keywords:
        keep = True
        to_remove = None

        for existing in selected:
            if _is_subphrase(kw, existing):
                keep = False
                break
            if _is_subphrase(existing, kw):
                to_remove = existing
                break

        if keep:
            if to_remove is not None:
                selected.remove(to_remove)
            selected.append(kw)

    return selected


# ── Primary path: SGRank + YAKE combined, POS-validated ──────────────────

def _extract_hybrid(text: str, top_n: int = 20) -> list[str] | None:
    """Combined textacy SGRank + YAKE, with spaCy POS validation."""
    nlp = _get_spacy_nlp()
    if nlp is None:
        return None

    try:
        import textacy
        from textacy.extract import keyterms as kt
    except ImportError:
        log.warning("textacy not installed; falling back to YAKE")
        return None

    doc = textacy.make_spacy_doc(text[:nlp.max_length], lang=nlp)
    noun_set = _build_noun_set(doc)
    scores: dict[str, float] = {}

    def _score(term_text: str, weight: float):
        cleaned = _clean_term(term_text)
        if not cleaned or not _has_noun(cleaned, noun_set):
            return
        refined = _refine_with_pos(cleaned, noun_set)
        if refined:
            scores[refined] = scores.get(refined, 0) + weight

    # SGRank: graph-based, POS-aware candidates (high confidence)
    sgrank_terms = kt.sgrank(doc, ngrams=(1, 2, 3), topn=top_n * 2)
    for term_text, score in sgrank_terms:
        _score(term_text, score * 3.0)

    # YAKE: statistical prominence (cross-validates with SGRank)
    yake_raw = _get_yake_extractor().extract_keywords(text)
    for term_text, yake_score in yake_raw:
        inv_score = 1.0 / (1.0 + yake_score)
        _score(term_text, inv_score * 1.5)

    # Named entities: always valuable (names, orgs, products, etc.)
    for ent in doc.ents:
        if ent.label_ in ("ORG", "PRODUCT", "PERSON", "GPE", "EVENT",
                           "WORK_OF_ART", "FAC", "LOC", "NORP"):
            cleaned = _clean_term(ent.text)
            if cleaned:
                scores[cleaned] = scores.get(cleaned, 0) + 2.0

    ranked = sorted(scores, key=lambda k: scores[k], reverse=True)
    return ranked[:top_n * 2]


# ── Fallback path: YAKE only (no spaCy available) ───────────────────────

_YAKE_STOPWORDS = {
    "i", "me", "my", "we", "our", "you", "your", "he", "him", "his",
    "she", "her", "it", "its", "they", "them", "their",
    "this", "that", "these", "those",
    "am", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did",
    "a", "an", "the", "and", "but", "if", "or", "as",
    "of", "at", "by", "for", "with", "about", "to", "from",
    "in", "out", "on", "off", "up", "down",
    "all", "each", "few", "more", "most", "other", "some", "no",
    "not", "only", "same", "so", "than", "too", "very",
    "can", "will", "just", "should", "now", "also",
    "first", "last", "today", "yesterday", "tomorrow",
    "give", "gave", "get", "got", "make", "made", "take", "took",
    "say", "said", "see", "saw", "let", "put", "go", "went", "come", "came",
    "look", "looked", "seem", "seemed",
    "good", "bad", "new", "old", "big", "small", "long", "short",
    "high", "low", "large", "great", "whole", "entire",
    "main", "major", "minor", "real", "important", "productive",
    "final", "middle", "second", "every", "one", "about",
}


def _extract_yake_fallback(text: str, top_n: int = 20) -> list[str]:
    """YAKE-only extraction with aggressive noise filtering."""
    raw = _get_yake_extractor().extract_keywords(text)
    keywords = [kw for kw, _score in sorted(raw, key=lambda x: x[1])]

    result = []
    for kw in keywords:
        cleaned = _clean_term(kw)
        if cleaned is None:
            continue
        words = cleaned.split()
        if len(words) == 1 and cleaned in _YAKE_STOPWORDS:
            continue
        result.append(cleaned)

    return result[:top_n * 2]


# ── Public API ───────────────────────────────────────────────────────────

def extract_keywords(text: str, top_n: int = 20) -> list[str]:
    """Extract keywords using SGRank + YAKE hybrid (primary) or YAKE-only (fallback).

    Returns a deduplicated, pruned list of up to ``top_n`` keywords.
    """
    keywords = _extract_hybrid(text, top_n)

    if keywords is None:
        keywords = _extract_yake_fallback(text, top_n)

    return prune_keywords(keywords)[:top_n]


if __name__ == "__main__":
    text1 = "bits and bit and the same as thing and things but all activities should be consider as the main priority which doesn't give any SD-WAN stuff or Nexus stuff"

    text2 = """ Test Case: A General Discussion Regarding Some Stuff and Other Things

The Opening Conversation
In this conversation today, I want to spend some time looking at something that happens quite often. It is a thing that we see every day, and sometimes even at night. When you think about the activity of daily life, there is always a few things that stand out. This time, however, I am not just talking about any specific activity; I am talking about the whole conversation surrounding how we handle anything that comes our way.


Exploring the Activity
A few days ago, I was thinking about that night when I realized that something was missing from my routine. The activity of organizing my schedule felt like a major thing, but it was actually just a few bits of planning that needed to be done. If you look at the stuff you do during the day, you will find that most of it is just repetitive activity. That night, I stayed up late looking at various things, trying to find anything that would make the process easier. This time, I found that the conversation I had with myself was the most important thing.


The Middle Bits
There are a few factors to consider when you are dealing with this kind of stuff. First, the time you spend on an activity matters. If you spend all day on one thing, you might miss out on something else. Second, anything you do at night should be different from what you do during the day. I've noticed that some people like to categorize their bits of work into "day stuff" and "night stuff." This conversation about categorization is something that has been going on for a long time.


A Few Final Things
To conclude this conversation, I want to mention a few more things. Anything can be turned into a productive activity if you give it enough time. Whether it is that night you spent working or this time you are spending reading this, every thing counts. We often get caught up in the bits and pieces of life, but the main thing is to keep moving forward. I hope this conversation helps you look at your daily activity and the stuff you do in a new way. There is always something new to learn about the things we do every day and night.
"""

    text3 = """Test Case: The Future of Networking Stuff and Other Things Introduction In this conversation today, I wanted to take some time to talk about something that has been on my mind for a few days. When we look at the activity of modern networking, there is always a new thing to consider. This time, I am focusing on how we handle the various bits of data that move through our systems at night and during the day. It is a conversation that many of us have had before, but I think this time it is different because of a few factors. The Main Activity When you are working with Cisco Catalyst switches or perhaps some Nexus stuff, you often run into a situation where you need to manage anything that comes across the wire. That night when I was reviewing the logs, I realized that the activity wasn't just about the hardware; it was about the software things as well. We often say that "time is money," but in networking, time is latency. If you don't fix the latency thing, you will have a bad day. I've noticed a few people mentioning that they want to see more technical bits in these posts. So, let's look at something specific. When we configure an interface, we aren't just doing a thing; we are establishing a protocol conversation. This conversation happens all the time, whether it is day or night. If anything goes wrong during this time, the whole activity could fail. A Few More Things to Consider There is always something new to learn about SD-WAN stuff. Last night, I was thinking about the conversation we had regarding security things. It's not just about one thing; it's about all the things combined. For instance, if you have a few routers that aren't synced, you'll spend a lot of time fixing the sync activity. This time, I recommend looking at the automation bits. Automation is the thing that will save us time in the long run. Anything can happen when you are deploying a new configuration. That night, we saw a few errors that didn't mean anything at first, but over time, they became a major thing. We spent the whole day looking at the activity logs, trying to find something—anything—that would explain the behavior. Conclusion To wrap this up, I hope this conversation provided a few insights into the stuff we do every day. Networking is a complex activity, and there is always something to improve. Next time, we will talk about more specific Cisco things and how to manage the bits and pieces of your infrastructure during the day. It has been a long night, but I think we have covered a lot of things."""
    
    text4 = """
The thing about the system is that it is always doing something, even when it does not look like anything is happening. During the day, the team talks about the activity, the process, the workflow, the work, the operations, the tasks, the things, the items, and the stuff, but at night the same team tends to discuss the same activity in slightly different words without adding much new information. This creates a situation where the summary of the situation becomes the thing that matters more than the actual thing itself, which is not always helpful.

In the first section of the report, the report talks about the process of processing the process, which is a common pattern in documents that describe operations, operations management, project coordination, coordination efforts, and effort management. The document mentions alignment, alignment strategies, strategic alignment, and strategic stuff, but it also mentions the bits and pieces of the team, the pieces of the workflow, the bits of the project, and the pieces of the project in a way that makes every sentence sound important even when the sentence is only repeating the same point in a different form. Sometimes the same idea appears as an aspect, then as an element, then as a factor, then as a detail, then as a part, then as a component, and then as a thing.

When we look at the data, the data is not always data in the strict sense. Sometimes data means a log, sometimes it means a note, sometimes it means a record, sometimes it means an output, sometimes it means a result, and sometimes it means a report that claims to explain the report. The logs show activity, but the activity may be an artifact of the logging system rather than the actual work. The output seems to match the output expected by the output checker, yet the checker itself may be using the same output as the source of truth, which creates a loop of self-reference that is difficult to resolve.

The organization says it wants efficiency, but efficiency is described using words like improvement, betterment, optimization, enhancement, coordination, integration, alignment, and synchronization. In one paragraph, integration is critical; in the next paragraph, coordination is critical; in the next paragraph, organization is critical; and in the next paragraph, communication is critical, even though all of these ideas are presented as if they are separate when they are really the same broad concept repeated with minor variation. The project team, the program team, the operations team, the delivery team, and the management team are all mentioned, but it is hard to tell whether they are distinct groups or just different names for the same group.

There is also a discussion about the implementation phase, the planning phase, the analysis phase, the review phase, the execution phase, and the closing phase, but each phase seems to contain the same checklist, the same notes, the same approvals, the same issues, and the same decisions. At one point the text says something happened during the day; later it says the same thing happened at night; then it says it happened last night; then it says it happened yesterday; then it says it happened recently; then it says it happens often. These time references create movement without necessarily adding meaning. The document appears to describe progress, but progress is described as movement, and movement is described as change, and change is described as activity, and activity is described as work.

If you try to extract keywords from this text, you may notice that nearly every sentence contains a candidate keyword, but many of those candidates are too generic to be useful. The text deliberately repeats terms like thing, things, stuff, system, process, activity, report, data, team, work, result, output, log, note, point, part, element, factor, aspect, and issue. It also repeats phrases like strategic alignment, project management, workflow optimization, operational efficiency, coordination effort, integration layer, and management process, but not always in a way that makes them clearly more important than the surrounding filler. This makes it difficult to decide whether the right keyword is the repeated phrase, the broader theme, or the most specific noun in the sentence.

Another challenge is that the text frequently uses pronouns and vague references. It says this, that, these, those, it, they, one, another, each, every, some, many, few, several, various, and certain, often without a clear antecedent. Sometimes the text refers to the plan, sometimes the process, sometimes the strategy, sometimes the approach, sometimes the method, and sometimes the idea, but the actual target of the discussion is intentionally blurred. The result is a document where the surface vocabulary is rich but the semantic signal is weak.

Even the conclusion does not fully conclude anything. It restates the same pattern: there is a need for clarity, there is a need for better organization, there is a need for improved structure, and there is a need for more meaningful information. The final recommendation is to review the review, check the checklist, inspect the inspection notes, evaluate the evaluation process, and refine the refinement steps until the report becomes clearer. Whether that actually improves the content is another thing altogether.
"""

    # print("=== Short (noisy input) ===")
    # print("Keywords:", extract_keywords(text1, top_n=20))
    # print()
    # print("=== Generic / vague text ===")
    # print("Keywords:", extract_keywords(text2, top_n=20))
    # print()
    # print("=== Technical (networking) ===")
    # print("Keywords:", extract_keywords(text3, top_n=20))
    print()
    print("=== generic ===")
    print("Keywords:", extract_keywords(text4, top_n=20))
