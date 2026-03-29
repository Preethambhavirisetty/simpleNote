"""Hybrid keyword extraction for note ingestion.

Architecture
~~~~~~~~~~~~
A two-tier system with automatic fallback:

    Primary path  ─  textacy SGRank + YAKE + spaCy NER  (POS-validated)
    Fallback path ─  YAKE-only  (when spaCy/textacy are unavailable)

Both paths share the same cleaning, filtering, and pruning pipeline.

Libraries
~~~~~~~~~
*   **spaCy** (``en_core_web_sm``) — tokenization, POS tagging, NER, and
    lemmatization.  Loaded lazily on first call; if missing, the fallback
    path is used instead.
*   **textacy** — thin wrapper over spaCy that provides the SGRank
    algorithm.  Piggybacks on the already-loaded spaCy model so there is
    no additional model overhead.
*   **YAKE** (Yet Another Keyword Extractor) — unsupervised, statistical,
    language-independent extractor.  Used as a cross-validator in the
    primary path and as the sole extractor in the fallback path.

Extraction pipeline (primary path)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
1.  **SGRank** (``textacy.extract.keyterms.sgrank``) generates graph-based
    keyword candidates from 1-, 2-, and 3-grams.  These are weighted at
    ``score * 3.0`` because SGRank leverages spaCy's POS tags and
    dependency parse, producing high-confidence noun phrases.

2.  **YAKE** generates statistical keyword candidates scored by
    positional/frequency heuristics.  YAKE scores are inverted
    (``1 / (1 + score)``) and weighted at ``* 1.5``.  This cross-validates
    SGRank: terms surfaced by both methods accumulate higher combined
    scores.

3.  **Named Entity Recognition** boosts entities with labels ORG, PRODUCT,
    PERSON, GPE, EVENT, WORK_OF_ART, FAC, LOC, NORP by a flat ``+2.0``.
    Named entities are always topically valuable (company names, product
    names, locations, etc.).

4.  Candidates are ranked by combined score and the top ``2 * top_n`` are
    passed to the pruning stage.

Noise filtering (domain-independent)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Rather than enumerating every possible noise word, the system uses POS-based
validation as its primary defense:

*   **``_has_noun``** — every candidate must contain at least one word that
    spaCy tagged as NOUN or PROPN in the source document.  This rejects
    verb-only, adverb-only, and pronoun-only candidates without needing to
    maintain a blacklist of every such word.

*   **``_refine_with_pos``** — strips non-noun words from the leading and
    trailing edges of multi-word phrases (e.g. "process easy" → "process",
    "specific cisco" → "cisco").  For phrases with 3+ words, interior
    verbs are also removed if the word is tagged as VERB but *not* also
    used as a NOUN elsewhere in the document.  This handles sentence
    fragments leaking through (e.g. "document mentions alignment" →
    "document alignment") while preserving dual-use words like "report"
    or "process" that function as both nouns and verbs.

*   **``_clean_term``** — normalises whitespace, lowercases, strips
    function words / vague nouns from edges, caps phrases at 4 words, and
    blocks standalone single-word noise.

The static filter sets exist as a safety net for words that POS tagging
alone cannot catch:

*   ``_NOISE_NOUNS`` — blocks standalone single-word keywords only (e.g.
    "thing", "stuff", "day", "process").  Multi-word phrases containing
    these words are allowed (e.g. "test case" survives even though "case"
    is in the set).

*   ``_VAGUE_TRAIL`` — stripped from both edges of compound phrases.
    Contains words that are genuinely meaningless at phrase boundaries
    (e.g. "thing", "stuff", "bit", "day").

*   ``_FUNC_WORDS`` — function words (articles, prepositions, pronouns)
    plus common verbs in past/present forms.  Stripped from leading
    positions.  Adjectives like "main", "new", "specific" are deliberately
    excluded so phrases like "main priority" survive.

*   ``_LEAD_STRIP`` / ``_TRAIL_STRIP`` — unions of ``_FUNC_WORDS`` and
    ``_VAGUE_TRAIL``, used for edge stripping in ``_clean_term``.

Subphrase pruning
~~~~~~~~~~~~~~~~~
After scoring, ``prune_keywords`` removes redundant terms:

*   If a candidate is a **subset** of an already-selected keyword (by
    stemmed token bag), it is skipped.

*   If a new candidate **subsumes** one or more already-selected keywords,
    those shorter keywords are replaced by the longer one.

Token comparison uses ``_stem`` — a lightweight normaliser that handles
common English plurals (``-s``, ``-es``, ``-ies``, ``-ches``, ``-shes``,s
``-ses``, ``-xes``, ``-zes``).  This collapses "switch"/"switches",
"log"/"logs", "activity"/"activities" etc. without requiring a full
lemmatizer in the pruning layer.  Hyphenated terms (e.g. "sd-wan") are
split into component tokens so "wan" is correctly recognised as a
subphrase of "sd-wan".

Design decisions
~~~~~~~~~~~~~~~~
*   **Why SGRank over TextRank?**  SGRank uses spaCy's POS tags to weight
    edges in the co-occurrence graph, producing more noun-phrase-oriented
    candidates.  TextRank treats all tokens equally.

*   **Why keep YAKE alongside SGRank?**  SGRank can miss statistically
    prominent terms that appear in unusual syntactic positions.  YAKE is
    syntax-blind and catches these.  The combined scoring lets both methods
    vote, improving recall without hurting precision.

*   **Why POS validation instead of bigger blacklists?**  Blacklists are
    domain-specific and play whack-a-mole.  POS validation is
    domain-independent: if spaCy didn't tag a word as a noun anywhere in
    the document, it is almost certainly not a topical keyword.  The small
    remaining blacklists catch edge cases where common nouns (like "thing",
    "stuff") are technically tagged as NOUN but carry no topical meaning.

*   **Why lazy loading?**  spaCy model loading takes ~1s.  Since keyword
    extraction runs during background ingestion, the cost is paid once and
    amortised across all subsequent calls.

*   **Why YAKE fallback?**  In environments where spaCy or textacy cannot
    be installed (e.g. minimal Docker images), the system degrades
    gracefully to YAKE-only extraction with aggressive stopword filtering
    rather than failing entirely.

Public API
~~~~~~~~~~
``extract_keywords(text, top_n=20) -> list[str]``
    Returns up to ``top_n`` deduplicated, pruned keywords ordered by
    relevance.  Called by ``chunking_service.py`` during note ingestion.

terms to understand: pruning, NER, lemmatization, tokenization, 1-,2-,3- grams, inverted scores, entity label_ in spacy, function words, stemmed tokens, subsumes, _stem
"""

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
        lower = token.text
        lemma = token.lemma_
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
    term = re.sub(r'\s+', ' ', term).strip()

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


_ENTITY_LABELS = frozenset({
    "ORG", "PRODUCT", "PERSON", "GPE", "EVENT",
    "WORK_OF_ART", "FAC", "LOC", "NORP",
})


def extract_entities(text: str, doc=None) -> list[str]:
    """Extract named entities from text, deduplicated and cleaned.

    If a pre-built spaCy/textacy doc is provided, it is reused to avoid
    double-processing.  Returns ``[]`` when spaCy is unavailable.
    """
    if doc is None:
        nlp = _get_spacy_nlp()
        if nlp is None:
            return []
        try:
            import textacy
        except ImportError:
            return []
        doc = textacy.make_spacy_doc(text[:nlp.max_length], lang=nlp)

    seen: set[str] = set()
    entities: list[str] = []
    for ent in doc.ents:
        if ent.label_ in _ENTITY_LABELS:
            cleaned = _clean_term(ent.text)
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                entities.append(cleaned)
    return entities



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

def _extract_hybrid(text: str, top_n: int = 20) -> tuple[list[str], list[str]] | None:
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

    entities = extract_entities(text, doc)
    for entity in entities:
        scores[entity] = scores.get(entity, 0) + 2.0

    ranked = sorted(scores, key=lambda k: scores[k], reverse=True)
    return ranked[:top_n * 2], entities


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

def extract_keywords(text: str, top_n: int = 20) -> tuple[list[str], list[str]]:
    """Extract keywords and named entities from text.

    Returns ``(keywords, entities)`` where *keywords* is a deduplicated,
    pruned list of up to ``top_n`` keywords and *entities* is a list of
    named entities (ORG, PERSON, GPE, etc.).  Entities are ``[]`` when
    spaCy is unavailable.
    """
    result = _extract_hybrid(text, top_n)

    if result is not None:
        keywords, entities = result
    else:
        keywords = _extract_yake_fallback(text, top_n)
        entities = []

    return prune_keywords(keywords)[:top_n], entities

if __name__ == '__main__':
    text = """
The project team is described in several ways. Sometimes it is the operations team. Sometimes it is the management team. Sometimes it is the delivery team. Sometimes it is simply the team.
"""
    import time
    start = time.time()
    kws, entities = extract_keywords(text)
    print(f"total words: {len(text.split())}, total processing time: {time.time() - start}")
    print(kws, len(kws))
    print(entities, len(entities))