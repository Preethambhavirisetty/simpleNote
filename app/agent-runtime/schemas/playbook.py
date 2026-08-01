"""Runtime-side view of the playbook contract served by agent-domain.

These mirror `agent-domain/schemas/playbook_schema.py` but are deliberately
lenient: the domain forbids unknown keys because it authors the catalog, while
the runtime ignores them so the domain can add a field without breaking a
deployed runtime.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class PlaybookStep(ContractModel):
    step: str
    operation: str | None = None


class PlaybookPlan(ContractModel):
    name: str
    description: str
    steps: list[PlaybookStep]


class Playbook(ContractModel):
    playbook_id: str
    name: str
    description: str
    examples: list[str] = []
    plans: list[PlaybookPlan] = []


class PlaybookMatch(ContractModel):
    playbook: Playbook
    score: float


class PlaybookCandidates(ContractModel):
    selection_mode: Literal["all", "semantic"]
    playbooks: list[Playbook]


class PlaybookSelection(BaseModel):
    """The routing decision for one request, validated against the catalog."""

    playbook_id: str
    plan_name: str
    reason: str
    # How the candidate list was produced, or "fallback" when the model's
    # answer was unusable and the grounded default was taken instead.
    selection_mode: Literal["all", "semantic", "fallback"]
    # LLM calls spent on this decision, including any retry.
    llm_calls: int = 1
