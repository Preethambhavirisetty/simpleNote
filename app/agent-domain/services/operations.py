from __future__ import annotations

from fastapi import HTTPException

from schemas.catalog_schema import Operation
from utils import build_model, named_entries, read_catalog_section


class OperationService:
    def get_operations(self) -> list[Operation]:
        section = read_catalog_section("operations.yaml", "operations", "Operation")
        return [
            build_model(Operation, entry, f"Operation '{entry['name']}'")
            for entry in named_entries(section, "Operation")
        ]

    def get_operation(self, name: str) -> Operation:
        for operation in self.get_operations():
            if operation.name == name:
                return operation
        raise HTTPException(status_code=404, detail="Operation Not Found")
