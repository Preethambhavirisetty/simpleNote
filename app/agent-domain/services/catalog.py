from __future__ import annotations

from schemas.catalog_schema import Catalog
from services.mappings import MappingService
from services.operations import OperationService
from services.playbook import PlaybookService
from services.steps import StepService


class CatalogService:
    """Composes the four catalogs and checks that they agree with each other."""

    def __init__(
        self,
        playbook_service: PlaybookService,
        operation_service: OperationService,
        mapping_service: MappingService,
        step_service: StepService,
    ) -> None:
        self._playbooks = playbook_service
        self._operations = operation_service
        self._mappings = mapping_service
        self._steps = step_service

    def get_catalog(self) -> Catalog:
        """The whole domain in one payload, so the runtime boots with one call."""
        return Catalog(
            steps=self._steps.get_steps(),
            operations=self._operations.get_operations(),
            mappings=self._mappings.get_mappings(),
            playbooks=self._playbooks.list_playbooks(),
        )

    def validate_catalog(self) -> list[str]:
        """Cross-catalog references that no single file can check on its own."""
        catalog = self.get_catalog()
        step_kinds = {step.name: step.kind for step in catalog.steps}
        operation_names = {operation.name for operation in catalog.operations}

        problems: list[str] = []
        problems += self._mapping_problems(catalog, operation_names)
        problems += self._playbook_problems(catalog, step_kinds, operation_names)
        return problems

    @staticmethod
    def _mapping_problems(catalog: Catalog, operation_names: set[str]) -> list[str]:
        problems: list[str] = []
        mapped: set[str] = set()

        for mapping in catalog.mappings:
            if mapping.operation in mapped:
                problems.append(f"mappings.yaml: duplicate mapping for '{mapping.operation}'")
            mapped.add(mapping.operation)
            if mapping.operation not in operation_names:
                problems.append(
                    f"mappings.yaml: '{mapping.operation}' is not in operations.yaml"
                )

        for name in sorted(operation_names - mapped):
            problems.append(f"operations.yaml: '{name}' has no mapping to a tool")

        return problems

    @staticmethod
    def _playbook_problems(
        catalog: Catalog, step_kinds: dict[str, str], operation_names: set[str]
    ) -> list[str]:
        problems: list[str] = []

        for playbook in catalog.playbooks:
            where = f"playbooks/{playbook.playbook_id}"
            plan_names: set[str] = set()

            for plan in playbook.plans:
                if plan.name in plan_names:
                    problems.append(f"{where}: duplicate plan '{plan.name}'")
                plan_names.add(plan.name)

                for step in plan.steps:
                    location = f"{where}: plan '{plan.name}' step '{step.step}'"
                    kind = step_kinds.get(step.step)

                    if kind is None:
                        problems.append(f"{location} is not in steps.yaml")
                    elif kind == "operation" and step.operation is None:
                        problems.append(f"{location} must name an operation")
                    elif kind != "operation" and step.operation is not None:
                        problems.append(
                            f"{location} is a {kind} step and cannot name an operation"
                        )

                    if step.operation is not None and step.operation not in operation_names:
                        problems.append(
                            f"{location} names unknown operation '{step.operation}'"
                        )

        return problems
