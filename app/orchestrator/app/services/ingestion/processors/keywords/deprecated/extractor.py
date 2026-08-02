from __future__ import annotations

import logging

from app.services.ingestion.processors.keywords.terms import (
    NOISE_NOUNS,
    clean_term,
    prune_keywords,
)


log = logging.getLogger(__name__)

_spacy_nlp = None
_yake_extractor = None
_yake_top = 0
_yake_unavailable = False

ENTITY_LABELS = frozenset(
    {
        "ORG",
        "PRODUCT",
        "PERSON",
        "GPE",
        "EVENT",
        "WORK_OF_ART",
        "FAC",
        "LOC",
        "NORP",
    }
)

YAKE_STOPWORDS = {
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


def get_spacy_nlp():
    global _spacy_nlp
    if _spacy_nlp is None:
        try:
            import spacy

            _spacy_nlp = spacy.load("en_core_web_sm")
        except (ImportError, OSError):
            log.warning("spaCy model not available; falling back to YAKE-only keywords")
            _spacy_nlp = False
    return _spacy_nlp if _spacy_nlp is not False else None


def get_yake_extractor(min_top: int = 20):
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


def build_pos_sets(doc) -> tuple[set[str], set[str]]:
    nouns = set()
    verbs = set()
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


def has_noun(term: str, noun_set: set[str]) -> bool:
    for word in term.split():
        lowered = word.lower()
        if lowered in noun_set:
            return True
        if "-" in lowered and any(part in noun_set for part in lowered.split("-") if part):
            return True
    return False


def refine_with_pos(term: str, noun_set: set[str], verb_set: set[str]) -> str | None:
    words = term.split()
    if len(words) <= 1:
        return term

    while len(words) > 1 and words[-1].lower() not in noun_set:
        words.pop()
    while len(words) > 1 and words[0].lower() not in noun_set:
        words.pop(0)

    if len(words) >= 3:
        words = [
            word
            for index, word in enumerate(words)
            if index == 0
            or index == len(words) - 1
            or word.lower() not in verb_set
            or word.lower() in noun_set
        ]

    term = " ".join(words)
    if not term or len(term) < 3:
        return None
    if len(words) == 1 and term.lower() in NOISE_NOUNS:
        return None
    return term


def extract_entities(text: str, doc=None) -> list[str]:
    if doc is None:
        nlp = get_spacy_nlp()
        if nlp is None:
            return []
        try:
            import textacy
        except ImportError:
            return []
        doc = textacy.make_spacy_doc(text[: nlp.max_length], lang=nlp)

    seen = set()
    entities = []
    for ent in doc.ents:
        if ent.label_ in ENTITY_LABELS:
            cleaned = clean_term(ent.text)
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                entities.append(cleaned)
    return entities


def extract_hybrid(text: str, top_n: int = 20) -> tuple[list[str], list[str]] | None:
    nlp = get_spacy_nlp()
    if nlp is None:
        return None

    try:
        import textacy
        from textacy.extract import keyterms
    except ImportError:
        log.warning("textacy not installed; falling back to YAKE")
        return None

    doc = textacy.make_spacy_doc(text[: nlp.max_length], lang=nlp)
    noun_set, verb_set = build_pos_sets(doc)
    scores = {}

    def score_term(term_text: str, weight: float) -> None:
        cleaned = clean_term(term_text)
        if not cleaned or not has_noun(cleaned, noun_set):
            return
        refined = refine_with_pos(cleaned, noun_set, verb_set)
        if refined:
            scores[refined] = scores.get(refined, 0) + weight

    for term_text, score in keyterms.sgrank(doc, ngrams=(1, 2, 3), topn=top_n * 2):
        score_term(term_text, score * 3.0)

    yake_extractor = get_yake_extractor(max(top_n * 2, 20))
    if yake_extractor is not None:
        for term_text, yake_score in yake_extractor.extract_keywords(text):
            score_term(term_text, (1.0 / (1.0 + yake_score)) * 1.5)

    entities = extract_entities(text, doc)
    for entity in entities:
        scores[entity] = scores.get(entity, 0) + 2.0

    ranked = sorted(scores, key=lambda key: scores[key], reverse=True)
    return ranked[: top_n * 2], entities


def extract_yake_fallback(text: str, top_n: int = 20) -> list[str]:
    extractor = get_yake_extractor(max(top_n * 2, 20))
    if extractor is None:
        return []

    raw = extractor.extract_keywords(text)
    keywords = [keyword for keyword, _score in sorted(raw, key=lambda item: item[1])]

    result = []
    for keyword in keywords:
        cleaned = clean_term(keyword)
        if cleaned is None:
            continue
        if len(cleaned.split()) == 1 and cleaned in YAKE_STOPWORDS:
            continue
        result.append(cleaned)

    return result[: top_n * 2]


def extract_keywords(text: str, top_n: int = 20) -> tuple[list[str], list[str]]:
    result = extract_hybrid(text, top_n)

    if result is not None:
        keywords, entities = result
    else:
        keywords = extract_yake_fallback(text, top_n)
        entities = []

    return prune_keywords(keywords)[:top_n], entities
