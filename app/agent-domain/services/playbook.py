from __future__ import annotations

import json
from math import sqrt
from pathlib import Path
from threading import Lock

from fastapi import HTTPException

from integrations.embedder import embed_texts
from utils import CatalogNotFoundError, list_child_dirs, read_yaml


PLAYBOOK_EMBEDDINGS_FILE = (
    Path(__file__).resolve().parents[1] / "assets" / "playbook_embeddings.json"
)


class PlaybookService:
    def __init__(self) -> None:
        self._embeddings: dict[str, list[float]] | None = None
        self._embedding_lock = Lock()

    def _playbook_path(self, playbook_id: str) -> str:
        return f"playbooks/{playbook_id}/playbook.yaml"

    def _playbook_ids(self) -> list[str]:
        try:
            return list_child_dirs("playbooks")
        except CatalogNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Playbook Catalog Not Found") from exc
        except NotADirectoryError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    def get_playbook(self, playbook_id: str) -> dict:
        if (
            not playbook_id
            or "/" in playbook_id
            or "\\" in playbook_id
            or playbook_id in {".", ".."}
        ):
            raise HTTPException(status_code=404, detail="Playbook Not Found")

        try:
            return read_yaml(self._playbook_path(playbook_id))
        except CatalogNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Playbook Not Found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    def list_playbooks(self) -> list[dict]:
        return [self.get_playbook(playbook_id) for playbook_id in self._playbook_ids()]

    @staticmethod
    def _embedding_text(playbook: dict) -> str:
        name = playbook.get("name", "")
        description = playbook.get("description", "")
        examples = playbook.get("examples", [])
        if isinstance(examples, list):
            examples_text = "\n".join(str(example) for example in examples)
        else:
            examples_text = str(examples)
        return f"name: {name}\ndescription: {description}\nexamples:\n{examples_text}"

    def _save_embeddings(self, embeddings: dict[str, list[float]]) -> None:
        PLAYBOOK_EMBEDDINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary_file = PLAYBOOK_EMBEDDINGS_FILE.with_suffix(".json.tmp")
        with temporary_file.open("w", encoding="utf-8") as file:
            json.dump(embeddings, file, indent=2, sort_keys=True)
        temporary_file.replace(PLAYBOOK_EMBEDDINGS_FILE)

    def _load_embeddings(self) -> dict[str, list[float]]:
        if not PLAYBOOK_EMBEDDINGS_FILE.is_file():
            return {}

        try:
            with PLAYBOOK_EMBEDDINGS_FILE.open("r", encoding="utf-8") as file:
                payload = json.load(file)
        except (json.JSONDecodeError, OSError):
            return {}

        if not isinstance(payload, dict):
            return {}

        embeddings: dict[str, list[float]] = {}
        for playbook_id, embedding in payload.items():
            if not isinstance(embedding, list):
                continue
            try:
                embeddings[str(playbook_id)] = [float(value) for value in embedding]
            except (TypeError, ValueError):
                continue
        return embeddings

    def generate_playbook_embeddings(self) -> dict[str, list[float]]:
        playbook_ids = self._playbook_ids()
        playbooks = [self.get_playbook(playbook_id) for playbook_id in playbook_ids]
        vectors = embed_texts([self._embedding_text(playbook) for playbook in playbooks])
        embeddings = dict(zip(playbook_ids, vectors, strict=True))
        self._save_embeddings(embeddings)
        self._embeddings = embeddings
        return embeddings

    def initialize_embeddings(self) -> None:
        if self._embeddings is not None:
            return

        with self._embedding_lock:
            if self._embeddings is not None:
                return

            cached = self._load_embeddings()
            playbook_ids = set(self._playbook_ids())
            if cached and set(cached) == playbook_ids:
                self._embeddings = cached
                return

            self.generate_playbook_embeddings()

    @staticmethod
    def _cosine_similarity(left: list[float], right: list[float]) -> float:
        if len(left) != len(right) or not left:
            return 0.0
        left_norm = sqrt(sum(value * value for value in left))
        right_norm = sqrt(sum(value * value for value in right))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)

    def search_playbooks(self, query: str, limit: int = 5) -> list[dict]:
        normalized_query = query.strip()
        if not normalized_query:
            raise HTTPException(status_code=422, detail="Search query must not be empty")

        self.initialize_embeddings()
        query_embedding = embed_texts([normalized_query])[0]
        embeddings = self._embeddings or {}

        ranked = sorted(
            (
                (playbook_id, self._cosine_similarity(query_embedding, embedding))
                for playbook_id, embedding in embeddings.items()
            ),
            key=lambda item: (-item[1], item[0]),
        )[:limit]

        return [
            {"playbook": self.get_playbook(playbook_id), "score": score}
            for playbook_id, score in ranked
        ]
