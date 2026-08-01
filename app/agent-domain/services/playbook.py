from __future__ import annotations

from threading import Lock

from fastapi import HTTPException

from config import PLAYBOOK_SEARCH_LIMIT
from integrations.embedder import embed_texts
from schemas.playbook_schema import Playbook, PlaybookMatch
from utils import (
    CATALOG_ROOT,
    CatalogNotFoundError,
    build_model,
    list_child_dirs,
    read_yaml,
)


class PlaybookService:
    """Reads playbooks from the catalog and ranks them against a question."""

    def __init__(self) -> None:
        self._embeddings: dict[str, list[float]] | None = None
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

    def search_playbooks(
        self, query: str, limit: int = PLAYBOOK_SEARCH_LIMIT
    ) -> list[PlaybookMatch]:
        question = query.strip()
        if not question:
            raise HTTPException(status_code=422, detail="Search query must not be empty")

        embeddings = self.initialize_embeddings()
        question_embedding = embed_texts([question])[0]

        ranked = sorted(
            (
                (playbook_id, self._similarity(question_embedding, embedding))
                for playbook_id, embedding in embeddings.items()
            ),
            key=lambda item: (-item[1], item[0]),
        )[:limit]

        return [
            PlaybookMatch(playbook=self.get_playbook(playbook_id), score=score)
            for playbook_id, score in ranked
        ]

    def initialize_embeddings(self) -> dict[str, list[float]]:
        """Embed every playbook once, at startup or on the first search."""
        if self._embeddings is not None:
            return self._embeddings

        with self._embedding_lock:
            if self._embeddings is None:
                playbooks = self.list_playbooks()
                vectors = embed_texts(
                    [self._embedding_text(playbook) for playbook in playbooks]
                )
                self._embeddings = {
                    playbook.playbook_id: vector
                    for playbook, vector in zip(playbooks, vectors, strict=True)
                }
            return self._embeddings

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
    def _embedding_text(playbook: Playbook) -> str:
        examples_text = "\n".join(playbook.examples)
        return (
            f"playbook_id: {playbook.playbook_id}\n"
            f"name: {playbook.name}\n"
            f"description: {playbook.description}\n"
            f"examples:\n{examples_text}"
        )

    @staticmethod
    def _similarity(left: list[float], right: list[float]) -> float:
        # embed_texts returns L2-normalised vectors, so the dot product is the cosine.
        return sum(a * b for a, b in zip(left, right, strict=True))
