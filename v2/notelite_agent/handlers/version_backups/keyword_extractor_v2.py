import re
import logging

log = logging.getLogger(__name__)

_spacy_nlp = None
_yake_extractor = None
_yake_top = 0
_yake_unavailable = False

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


def _get_yake_extractor(min_top: int = 20):
    global _yake_extractor, _yake_top, _yake_unavailable
    if _yake_unavailable:
        return None
    if _yake_extractor is None or _yake_top < min_top:
        try:
            import yake
        except ImportError:
            log.warning("YAKE not installed; keyword extraction unavailable")
            _yake_unavailable = True
            return None
        _yake_extractor = yake.KeywordExtractor(
            lan="en",
            n=3,
            top=min_top,
            dedupLim=0.7,
        )
        _yake_top = min_top
    return _yake_extractor


# ── POS validation ───────────────────────────────────────────────────────

def _build_pos_sets(doc) -> tuple[set[str], set[str]]:
    """Build noun and verb sets from a spaCy doc for POS validation."""
    nouns: set[str] = set()
    verbs: set[str] = set()
    for token in doc:
        lower = token.text.lower()
        lemma = token.lemma_.lower()
        if token.pos_ in ("NOUN", "PROPN") and not token.is_stop:
            nouns.add(lemma)
            nouns.add(lower)
        elif token.pos_ == "VERB":
            verbs.add(lemma)
            verbs.add(lower)
    return nouns, verbs


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


def _refine_with_pos(term: str, noun_set: set[str], verb_set: set[str]) -> str | None:
    """Strip non-noun edges and interior verbs from multi-word terms.

    Handles YAKE artifacts like 'process easy' → 'process',
    'specific cisco' → 'cisco',
    and 'document mentions alignment' → 'document alignment'.
    """
    words = term.split()
    if len(words) <= 1:
        return term

    while len(words) > 1 and words[-1] not in noun_set:
        words.pop()

    while len(words) > 1 and words[0] not in noun_set:
        words.pop(0)

    if len(words) >= 3:
        words = [
            w for i, w in enumerate(words)
            if i == 0 or i == len(words) - 1
            or w not in verb_set or w in noun_set
        ]

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

def _stem(word: str) -> str:
    """Crude singular normalization for subphrase deduplication."""
    if word.endswith('ies') and len(word) > 4:
        return word[:-3] + 'y'
    if len(word) > 4:
        for suffix in ('ches', 'shes', 'ses', 'xes', 'zes'):
            if word.endswith(suffix):
                return word[:-2]
    if word.endswith('s') and not word.endswith('ss') and len(word) > 3:
        return word[:-1]
    return word


def _split_tokens(phrase: str) -> set[str]:
    tokens = set()
    for word in phrase.split():
        tokens.add(_stem(word))
        if '-' in word:
            tokens.update(_stem(part) for part in word.split('-') if part)
    return tokens


def _is_subphrase(a: str, b: str) -> bool:
    return _split_tokens(a).issubset(_split_tokens(b))


def prune_keywords(keywords: list[str]) -> list[str]:
    if not keywords:
        return []

    selected: list[str] = []
    for kw in keywords:
        keep = True
        to_remove: list[str] = []

        for existing in selected:
            if _is_subphrase(kw, existing):
                keep = False
                break
            if _is_subphrase(existing, kw):
                to_remove.append(existing)

        if keep:
            for existing in to_remove:
                selected.remove(existing)
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
    noun_set, verb_set = _build_pos_sets(doc)
    scores: dict[str, float] = {}

    def _score(term_text: str, weight: float):
        cleaned = _clean_term(term_text)
        if not cleaned or not _has_noun(cleaned, noun_set):
            return
        refined = _refine_with_pos(cleaned, noun_set, verb_set)
        if refined:
            scores[refined] = scores.get(refined, 0) + weight

    # SGRank: graph-based, POS-aware candidates (high confidence)
    sgrank_terms = kt.sgrank(doc, ngrams=(1, 2, 3), topn=top_n * 2)
    for term_text, score in sgrank_terms:
        _score(term_text, score * 3.0)

    # YAKE: statistical prominence (cross-validates with SGRank)
    yake_extractor = _get_yake_extractor(max(top_n * 2, 20))
    if yake_extractor is not None:
        yake_raw = yake_extractor.extract_keywords(text)
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
    extractor = _get_yake_extractor(max(top_n * 2, 20))
    if extractor is None:
        return []

    raw = extractor.extract_keywords(text)
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
The document begins with the idea that the organization is always doing something, even when it is not doing very much at all. On paper, the system appears organized, but in practice the system is mostly a collection of activities, operations, processes, notes, reports, and discussions that are repeated in different forms throughout the day. During the day, the team talks about coordination, and at night the same team talks about coordination again, but with slightly different words, as if repetition itself were a strategy. The report about the work refers to the report as if the report were both the cause and the effect of the work.

In the first section, there is a mention of alignment, strategy, management, implementation, workflow, integration, and output. In the second section, those same terms appear again, but they are surrounded by words like thing, stuff, part, item, element, factor, aspect, and piece. The text keeps saying that one thing leads to another thing, that one activity influences another activity, and that one operation affects another operation, yet the exact relationship between these things is never fully explained. The result is a situation where the situation itself becomes the subject of the discussion.

The project team is described in several ways. Sometimes it is the operations team. Sometimes it is the management team. Sometimes it is the delivery team. Sometimes it is simply the team. Sometimes it is not even a team but a group, a unit, a collection, or a set of people working on the same thing. The document also refers to the organization, the company, the department, the office, and the group as though these were interchangeable, which makes entity extraction difficult. The organization wants better organization, the company wants better coordination, and the department wants better management, but all of these goals are expressed using the same generic language.

There are multiple references to the phase, the stage, the step, the process, the procedure, the cycle, and the sequence. Every phase contains a review, every review contains a note, every note contains a comment, every comment contains a remark, and every remark contains another reference to the same project. The implementation phase is mentioned alongside the planning phase, the analysis phase, the execution phase, the validation phase, and the closing phase, but each one seems to contain the same content repeated under a different heading. The document makes it look like there are many distinct stages when in reality there is very little variation.

The text also includes a long discussion of data, logs, records, outputs, results, metrics, values, and summaries. The data is said to support the report, but the report is also said to define the data. The logs are said to show the output, but the output is also said to confirm the logs. The metrics are said to measure performance, but performance is never clearly separated from activity, work, or output. This creates a loop in which every noun points back to another noun, and every conclusion points back to the original statement.

Sometimes the document switches to more abstract language. It talks about improvement, optimization, efficiency, quality, consistency, reliability, structure, clarity, and stability. These are repeated in different combinations, often with modifiers like better, more, less, stronger, clearer, faster, and simpler. The text claims that the workflow should be clearer, the operations should be smoother, the coordination should be stronger, the management should be better, and the integration should be tighter, but these claims are not backed by concrete detail. Instead, the document uses phrases like “the thing we need,” “the way forward,” “the right approach,” and “the better path,” which sound useful but do not add much semantic precision.

At several points, the document becomes circular. It says that the report should improve the report. It says that the summary should summarize the summary. It says that the review should review the review. It says that the process should process the process. It says that the system should stabilize the system. These statements are grammatically valid but semantically weak. They create a worst-case scenario for a keyword extractor because the same words appear in many contexts, often without clear importance or hierarchy.

The final section repeats the core themes one more time: team, report, work, process, system, output, management, operations, coordination, integration, workflow, phase, data, log, result, organization, and situation. The conclusion does not introduce new information; it only rephrases what has already been said. If a keyword extractor relies too heavily on frequency, it may surface the wrong terms. If it relies too heavily on shallow phrase matching, it may keep phrases that are merely repeated rather than truly meaningful. If it relies too heavily on surface form without normalization, it may treat plural and singular variants as unrelated terms even though they refer to the same concept.

In that sense, the document is designed to be difficult. It is long enough to create many candidate spans, repetitive enough to inflate common terms, abstract enough to blur semantic boundaries, and vague enough to make subphrase pruning uncertain. It includes multiple references to day and night, to the same idea expressed in different ways, to overlapping concepts like management and coordination, and to generic nouns like thing, stuff, part, piece, item, and element. A keyword extractor has to decide what matters most, even though the text keeps suggesting that almost everything matters equally. That is exactly what makes it a useful stress test.
"""

    print("=== Short (noisy input) ===")
    print("Keywords:", extract_keywords(text1, top_n=20))
    print()
    print("=== Generic / vague text ===")
    print("Keywords:", extract_keywords(text2, top_n=20))
    print()
    print("=== Technical (networking) ===")
    print("Keywords:", extract_keywords(text3, top_n=20))
    print()
    print("=== Adversarial (generic filler) ===")
    print("Keywords:", extract_keywords(text4, top_n=20))
