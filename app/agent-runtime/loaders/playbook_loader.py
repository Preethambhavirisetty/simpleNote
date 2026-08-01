from __future__ import annotations

from schemas.catalog import Catalog
from schemas.playbook import Playbook, PlaybookPlan
from utils import CatalogLookupError


class PlaybookLoader:
    """Lookups over the playbooks in a loaded catalog."""

    def __init__(self, catalog: Catalog) -> None:
        self._playbooks = {
            playbook.playbook_id: playbook for playbook in catalog.playbooks
        }

    def list_playbooks(self) -> list[Playbook]:
        return list(self._playbooks.values())

    def get_playbook(self, playbook_id: str) -> Playbook:
        try:
            return self._playbooks[playbook_id]
        except KeyError:
            known = ", ".join(sorted(self._playbooks)) or "none"
            raise CatalogLookupError(
                f"unknown playbook '{playbook_id}' (catalog has: {known})"
            ) from None

    def get_plan(self, playbook_id: str, plan_name: str) -> PlaybookPlan:
        playbook = self.get_playbook(playbook_id)
        for plan in playbook.plans:
            if plan.name == plan_name:
                return plan

        known = ", ".join(plan.name for plan in playbook.plans) or "none"
        raise CatalogLookupError(
            f"playbook '{playbook_id}' has no plan '{plan_name}' (has: {known})"
        )
