from __future__ import annotations

from fastapi import HTTPException

from utils import CatalogNotFoundError, read_yaml


class OperationService:
    def _operations_path(self) -> str:
        return "operations.yaml"

    def get_operations(self) -> dict:
        try:
            payload = read_yaml(self._operations_path())
        except CatalogNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Operation Catalog Not Found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        operations = payload.get("operations")
        if not isinstance(operations, dict):
            raise HTTPException(status_code=500, detail="Invalid Operations Catalog Format")

        return operations
