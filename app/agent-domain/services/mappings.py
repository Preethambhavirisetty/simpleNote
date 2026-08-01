from __future__ import annotations

from fastapi import HTTPException

from schemas.catalog_schema import Mapping
from utils import build_model, read_catalog_section


class MappingService:
    def get_mappings(self) -> list[Mapping]:
        section = read_catalog_section("mappings.yaml", "mappings", "Mapping")
        if not isinstance(section, list):
            raise HTTPException(status_code=500, detail="Invalid Mapping Catalog Format")

        return [
            build_model(Mapping, entry, f"Mapping #{position}")
            for position, entry in enumerate(section)
        ]

    def get_mapping(self, operation: str) -> Mapping:
        """The tool binding the runtime needs to execute one operation."""
        for mapping in self.get_mappings():
            if mapping.operation == operation:
                return mapping
        raise HTTPException(status_code=404, detail="Mapping Not Found")
