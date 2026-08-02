from __future__ import annotations

import logging
from dataclasses import dataclass
from threading import Lock

from fastapi import HTTPException

from config import PLAYBOOK_CANDIDATE_LIMIT, PLAYBOOK_SEARCH_LIMIT
from integrations.embedder import (
    EmbeddingsUnavailableError,
    embed_texts,
    embeddings_available,
)
from schemas.playbook_schema import Playbook, PlaybookCandidates, PlaybookMatch
from utils import (
    CATALOG_ROOT,
    CatalogNotFoundError,
    build_model,
    list_child_dirs,
    read_yaml,
)


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlaybookIndex:
    """Several vectors per playbook, and the corpus mean used to centre them.

    One vector per playbook does not work here: averaging a description with
    six unrelated examples pulls every playbook into the same narrow cone
    (measured at 0.44-0.72 cosine between playbooks), so a short question ranks
    them close to arbitrarily. Keeping the texts apart and scoring the best
    single match, on mean-centred vectors, measured 67% -> 78% top-1 and
    89% -> 98% recall@3 on a 45-question held-out set.
    """

    vectors: dict[str, list[list[float]]]
    mean: list[float]


class PlaybookService:
    """Reads playbooks from the catalog and ranks them against a question."""

    def __init__(self) -> None:
        self._index: PlaybookIndex | None = None
        self._embedding_lock = Lock()

    def get_playbook(self, playbook_id: str) -> Playbook:
        if (
            not playbook_id
            or "/" in playbook_id
            or "\\" in playbook_id
            or playbook_id in {".", ".."}
        ):
            raise HTTPException(status_code=404, detail="Playbook Not Found")

        try:
            payload = read_yaml(f"playbooks/{playbook_id}/playbook.yaml")
        except CatalogNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Playbook Not Found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        playbook = build_model(Playbook, payload, f"Playbook '{playbook_id}'")
        if playbook.playbook_id != playbook_id:
            raise HTTPException(
                status_code=500,
                detail=(
                    f"Playbook '{playbook_id}' declares playbook_id "
                    f"'{playbook.playbook_id}'"
                ),
            )
        return playbook

    def list_playbooks(self) -> list[Playbook]:
        return [self.get_playbook(playbook_id) for playbook_id in self._playbook_ids()]

    def get_candidates(self, query: str) -> PlaybookCandidates:
        """The playbooks worth showing a selector LLM for this question.

        Semantic similarity separates these playbooks by topic, but they differ
        by intent, so rank 1 is not trustworthy on its own. Search is therefore
        used for recall only, and skipped altogether while the whole catalog
        still fits in the selector's prompt.
        """
        # Validated up front, not just on the search path, so the contract does
        # not change the day the catalog outgrows the threshold.
        if not query.strip():
            raise HTTPException(status_code=422, detail="Search query must not be empty")

        playbooks = self.list_playbooks()
        if len(playbooks) <= PLAYBOOK_CANDIDATE_LIMIT:
            return PlaybookCandidates(selection_mode="all", playbooks=playbooks)

        if not embeddings_available():
            # Degrade rather than fail: a longer candidate list still routes
            # correctly, whereas a 500 here would take down every request.
            log.warning(
                "catalog of %d exceeds the candidate limit but embeddings are "
                "not installed; returning every playbook",
                len(playbooks),
            )
            return PlaybookCandidates(selection_mode="all", playbooks=playbooks)

        matches = self.search_playbooks(query, PLAYBOOK_CANDIDATE_LIMIT)
        return PlaybookCandidates(
            selection_mode="semantic",
            playbooks=[match.playbook for match in matches],
        )

    def search_playbooks(
        self, query: str, limit: int = PLAYBOOK_SEARCH_LIMIT
    ) -> list[PlaybookMatch]:
        question = query.strip()
        if not question:
            raise HTTPException(status_code=422, detail="Search query must not be empty")

        try:
            index = self.initialize_embeddings()
        except EmbeddingsUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        question_vector = self._centre(embed_texts([question])[0], index.mean)

        ranked = sorted(
            (
                (playbook_id, self._best_similarity(question_vector, vectors))
                for playbook_id, vectors in index.vectors.items()
            ),
            key=lambda item: (-item[1], item[0]),
        )[:limit]

        return [
            PlaybookMatch(playbook=self.get_playbook(playbook_id), score=score)
            for playbook_id, score in ranked
        ]

    def initialize_embeddings(self) -> PlaybookIndex:
        """Embed every playbook once, at startup or on the first search."""
        if self._index is not None:
            return self._index

        with self._embedding_lock:
            if self._index is None:
                self._index = self._build_index()
            return self._index

    def _build_index(self) -> PlaybookIndex:
        texts_by_playbook = {
            playbook.playbook_id: self._embedding_texts(playbook)
            for playbook in self.list_playbooks()
        }
        flattened = [
            text for texts in texts_by_playbook.values() for text in texts
        ]
        vectors = embed_texts(flattened)
        mean = self._mean(vectors)

        centred: dict[str, list[list[float]]] = {}
        offset = 0
        for playbook_id, texts in texts_by_playbook.items():
            centred[playbook_id] = [
                self._centre(vector, mean)
                for vector in vectors[offset : offset + len(texts)]
            ]
            offset += len(texts)

        return PlaybookIndex(vectors=centred, mean=mean)

    def _playbook_ids(self) -> list[str]:
        try:
            playbook_ids = list_child_dirs("playbooks")
        except CatalogNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Playbook Catalog Not Found") from exc
        except NotADirectoryError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        # Skip directories scaffolded for a playbook that is not written yet.
        return [
            playbook_id
            for playbook_id in playbook_ids
            if self._is_written(playbook_id)
        ]

    @staticmethod
    def _is_written(playbook_id: str) -> bool:
        playbook_file = CATALOG_ROOT / f"playbooks/{playbook_id}/playbook.yaml"
        return (
            playbook_file.is_file()
            and playbook_file.read_text(encoding="utf-8").strip() != ""
        )

    @staticmethod
    def _embedding_texts(playbook: Playbook) -> list[str]:
        """One text per routing signal, kept apart so none dilutes the others."""
        return [f"{playbook.name}. {playbook.description}", *playbook.examples]

    @staticmethod
    def _mean(vectors: list[list[float]]) -> list[float]:
        return [sum(values) / len(vectors) for values in zip(*vectors, strict=True)]

    @staticmethod
    def _centre(vector: list[float], mean: list[float]) -> list[float]:
        """Subtract the corpus mean and renormalise, so cosine spreads out."""
        shifted = [value - mean[position] for position, value in enumerate(vector)]
        norm = sum(value * value for value in shifted) ** 0.5
        if norm == 0:
            return shifted
        return [value / norm for value in shifted]

    @classmethod
    def _best_similarity(
        cls, question_vector: list[float], vectors: list[list[float]]
    ) -> float:
        return max(cls._similarity(question_vector, vector) for vector in vectors)

    @staticmethod
    def _similarity(left: list[float], right: list[float]) -> float:
        # Both sides are centred and renormalised, so the dot product is the cosine.
        return sum(a * b for a, b in zip(left, right, strict=True))
