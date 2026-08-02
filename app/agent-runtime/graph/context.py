"""What a run is given: the catalog, the router, and the step implementations."""

from __future__ import annotations

from dataclasses import dataclass, field

from loaders.operation_loader import OperationLoader
from loaders.playbook_loader import PlaybookLoader
from routing.playbook_selector import PlaybookSelector
from schemas.catalog import Catalog
from workflows.steps import (
    aggregation,
    direct_llm,
    direct_tool,
    execute_operation,
    resolve_filters,
    semantic_search,
    sort_by_date,
    summarize,
    validate_filters,
)
from workflows.steps.base import StepContext


# Step name -> implementation. The names are the domain's `steps.yaml`
# vocabulary; a plan can only name a step that appears here, and the catalog
# validator on the domain side keeps the two lists in agreement.
STEP_RUNNERS = {
    "direct_llm": direct_llm.run,
    "resolve_filters": resolve_filters.run,
    "summarize": summarize.run,
    "semantic_search": semantic_search.run,
    "execute_operation": execute_operation.run,
    "direct_tool": direct_tool.run,
    "validate_filters": validate_filters.run,
    "sort_by_date": sort_by_date.run,
    "aggregation": aggregation.run,
}


@dataclass
class RunContext:
    catalog: Catalog
    playbooks: PlaybookLoader = field(init=False)
    operations: OperationLoader = field(init=False)
    selector: PlaybookSelector = field(init=False)

    def __post_init__(self) -> None:
        self.playbooks = PlaybookLoader(self.catalog)
        self.operations = OperationLoader(self.catalog)
        self.selector = PlaybookSelector(self.playbooks)

    def steps(self, *, approved: bool = False) -> StepContext:
        return StepContext(
            operations=self.operations, playbooks=self.playbooks, approved=approved
        )

    def missing_steps(self) -> list[str]:
        """Steps the domain declares that this runtime cannot execute."""
        return sorted(
            step.name for step in self.catalog.steps if step.name not in STEP_RUNNERS
        )
