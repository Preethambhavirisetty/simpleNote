from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.services.ingestion.processors.keywords.terms import clean_term


log = logging.getLogger(__name__)

ENTITY_LABELS = frozenset({"PERSON", "ORG", "GPE", "LOC", "PRODUCT"})
ENTITY_NOISE = frozenset({"api", "doc", "eta", "gpu", "llm", "max", "metadata", "ram", "three", "utc"})
SYNTHETIC_PREFIXES = ("description ", "operation ", "pipeline message ", "resolution ", "variable ")

_spacy_nlp = None


@dataclass(frozen=True)
class EntityMention:
    text: str
    label: str


def get_spacy_nlp():
    global _spacy_nlp
    if _spacy_nlp is None:
        try:
            import spacy

            _spacy_nlp = spacy.load("en_core_web_sm")
        except (ImportError, OSError):
            log.warning("spaCy entity model is unavailable", exc_info=True)
            _spacy_nlp = False
    return _spacy_nlp if _spacy_nlp is not False else None


def extract_entities(text: str) -> list[str]:
    """Extract allowlisted named entities from normalized English text."""
    return [mention.text for mention in extract_entity_mentions_batch([text])[0]]


def extract_entities_batch(texts: list[str]) -> list[list[str]]:
    """Extract allowlisted entities from normalized texts with one spaCy pipeline."""
    return [[mention.text for mention in mentions] for mentions in extract_entity_mentions_batch(texts)]


def extract_entity_mentions_batch(texts: list[str]) -> list[list[EntityMention]]:
    """Extract allowlisted entity mentions with labels for final validation."""
    nlp = get_spacy_nlp()
    if nlp is None:
        return [[] for _ in texts]

    try:
        docs = nlp.pipe(text[: nlp.max_length] for text in texts)
        return [_entities_from_doc(doc) for doc in docs]
    except Exception:
        log.warning("spaCy entity extraction failed", exc_info=True)
        return [[] for _ in texts]


def _entities_from_doc(doc) -> list[EntityMention]:
    seen = set()
    entities = []
    for entity in doc.ents:
        if entity.label_ not in ENTITY_LABELS:
            continue
        cleaned = _clean_entity(entity.text, entity.label_)
        if cleaned and not _is_entity_noise(cleaned) and cleaned.lower() not in seen:
            seen.add(cleaned.lower())
            entities.append(EntityMention(cleaned, entity.label_))
    return entities


def _clean_entity(entity: str, label: str) -> str | None:
    cleaned = clean_term(entity)
    if cleaned and label == "PERSON":
        cleaned = re.sub(r"(?:'s|’s)$", "", cleaned).rstrip()
    return cleaned or None


def _is_entity_noise(entity: str) -> bool:
    lowered = entity.lower().strip()
    if lowered in ENTITY_NOISE or lowered.startswith(SYNTHETIC_PREFIXES):
        return True
    if ":*" in entity or re.search(r"(?:^|\s)[a-zA-Z]{1,2}(?:\s+[a-zA-Z]{1,2}){2,}", entity):
        return True
    return False
