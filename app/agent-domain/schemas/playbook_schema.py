"""Shapes for `playbooks/<playbook_id>/playbook.yaml`.

A playbook is the declarative answer to "what kind of request is this, and what
does the runtime do about it". It carries the routing surface (name,
description, examples) plus one or more plans; a plan is an ordered list of
steps, and a step optionally names an operation from the operation catalog.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlaybookStep(DomainModel):
    step: str
    operation: str | None = None


class PlaybookPlan(DomainModel):
    name: str
    description: str
    steps: list[PlaybookStep] = Field(min_length=1)


class Playbook(DomainModel):
    playbook_id: str
    name: str
    description: str
    examples: list[str] = Field(default_factory=list)
    plans: list[PlaybookPlan] = Field(min_length=1)


class PlaybookMatch(DomainModel):
    playbook: Playbook
    score: float


class PlaybookCandidates(DomainModel):
    """The playbooks a selector LLM should choose between for one question.

    `selection_mode` says how the list was produced: "all" when the catalog is
    small enough to show in full, "semantic" when search had to narrow it.
    Scores are deliberately omitted — ranking is a recall device here, and
    showing it to the selector only biases the choice.
    """

    selection_mode: Literal["all", "semantic"]
    playbooks: list[Playbook]
