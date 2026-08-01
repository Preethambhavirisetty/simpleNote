from __future__ import annotations

from fastapi import HTTPException

from utils import CatalogNotFoundError, read_yaml


class MappingService:
    def _mapping_path(self) -> str:
        return "mappings.yaml"

    def get_mappings(self) -> list[dict]:
        try:
            payload = read_yaml(self._mapping_path())
        except CatalogNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Mapping Catalog Not Found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        mappings = payload.get("mappings")
        if not isinstance(mappings, list):
            raise HTTPException(status_code=500, detail="Invalid Mapping Catalog Format")

        return mappings
