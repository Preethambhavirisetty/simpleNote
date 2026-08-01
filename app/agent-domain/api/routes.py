"""
GET  /api/domain/health
GET  /api/domain/catalog
GET  /api/domain/catalog/validation
GET  /api/domain/playbooks
GET  /api/domain/playbooks/{playbook_id}
POST /api/domain/playbooks/search
GET  /api/domain/operations
GET  /api/domain/operations/{name}
GET  /api/domain/mappings
GET  /api/domain/mappings/{operation}
GET  /api/domain/steps
GET  /api/domain/steps/{name}
"""

from typing import Annotated

from fastapi import APIRouter, Path
from pydantic import BaseModel, ConfigDict, Field

from config import PLAYBOOK_SEARCH_LIMIT
from schemas.catalog_schema import Catalog, Mapping, Operation, StepDefinition
from schemas.playbook_schema import Playbook, PlaybookMatch
from services.catalog import CatalogService
from services.mappings import MappingService
from services.operations import OperationService
from services.playbook import PlaybookService
from services.steps import StepService

router = APIRouter(prefix="/api/domain")
playbook_service = PlaybookService()
operation_service = OperationService()
mapping_service = MappingService()
step_service = StepService()
catalog_service = CatalogService(
    playbook_service, operation_service, mapping_service, step_service
)


class PlaybookSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    limit: int = Field(default=PLAYBOOK_SEARCH_LIMIT, ge=1, le=50)


class CatalogValidation(BaseModel):
    valid: bool
    problems: list[str]


@router.get("/health")
async def health():
    return {"status": "healthy"}


@router.get("/catalog")
async def get_catalog() -> Catalog:
    return catalog_service.get_catalog()


@router.get("/catalog/validation")
async def validate_catalog() -> CatalogValidation:
    problems = catalog_service.validate_catalog()
    return CatalogValidation(valid=not problems, problems=problems)


@router.get("/playbooks")
async def list_playbooks() -> list[Playbook]:
    return playbook_service.list_playbooks()


@router.post("/playbooks/search")
async def search_playbooks(request: PlaybookSearchRequest) -> list[PlaybookMatch]:
    return playbook_service.search_playbooks(request.query, request.limit)


@router.get("/playbooks/{playbook_id}")
async def get_playbook(playbook_id: Annotated[str, Path(min_length=1)]) -> Playbook:
    return playbook_service.get_playbook(playbook_id)


@router.get("/operations")
async def get_operations() -> list[Operation]:
    return operation_service.get_operations()


@router.get("/operations/{name}")
async def get_operation(name: Annotated[str, Path(min_length=1)]) -> Operation:
    return operation_service.get_operation(name)


@router.get("/mappings")
async def get_mappings() -> list[Mapping]:
    return mapping_service.get_mappings()


@router.get("/mappings/{operation}")
async def get_mapping(operation: Annotated[str, Path(min_length=1)]) -> Mapping:
    return mapping_service.get_mapping(operation)


@router.get("/steps")
async def get_steps() -> list[StepDefinition]:
    return step_service.get_steps()


@router.get("/steps/{name}")
async def get_step(name: Annotated[str, Path(min_length=1)]) -> StepDefinition:
    return step_service.get_step(name)
