from __future__ import annotations

from fastapi import HTTPException

from schemas.catalog_schema import StepDefinition
from utils import build_model, named_entries, read_catalog_section


class StepService:
    def get_steps(self) -> list[StepDefinition]:
        section = read_catalog_section("steps.yaml", "steps", "Step")
        return [
            build_model(StepDefinition, entry, f"Step '{entry['name']}'")
            for entry in named_entries(section, "Step")
        ]

    def get_step(self, name: str) -> StepDefinition:
        for step in self.get_steps():
            if step.name == name:
                return step
        raise HTTPException(status_code=404, detail="Step Not Found")
