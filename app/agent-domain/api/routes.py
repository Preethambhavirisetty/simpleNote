"""
GET /api/domain/health
GET /api/domain/playbooks
GET /api/domain/playbooks/{id}
POST /api/domain/playbooks/search
GET /api/domain/operations
GET /api/domain/mappings
"""

from typing import Annotated

from fastapi import APIRouter, Path
from pydantic import BaseModel, ConfigDict

from services.mappings import MappingService
from services.operations import OperationService
from services.playbook import PlaybookService

router = APIRouter(prefix="/api/domain")
playbook_service = PlaybookService()
operation_service = OperationService()
mapping_service = MappingService()


class PlaybookSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str


@router.get("/health")
async def health():
    return {"status": "healthy"}


@router.get("/playbooks")
async def list_playbooks():
    return playbook_service.list_playbooks()


@router.get("/playbooks/{playbook_id}")
async def get_playbook(playbook_id: Annotated[str, Path(min_length=1)]):
    return playbook_service.get_playbook(playbook_id)


@router.post("/playbooks/search")
async def search_playbooks(request: PlaybookSearchRequest):
    return playbook_service.search_playbooks(request.query)


@router.get("/operations")
async def get_operations():
    return operation_service.get_operations()


@router.get("/mappings")
async def get_mappings():
    return mapping_service.get_mappings()
