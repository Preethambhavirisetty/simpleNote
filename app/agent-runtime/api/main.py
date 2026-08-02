import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.routes import router, run_context
from integrations.domain import DomainUnavailableError

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm the catalog, but do not die if agent-domain is still starting:
    # compose has no ordering guarantee, and the first request will retry.
    try:
        context = run_context()
        log.info(
            "catalog loaded: %d playbooks, %d operations",
            len(context.catalog.playbooks),
            len(context.catalog.operations),
        )
        missing = context.missing_steps()
        if missing:
            log.warning("domain declares steps this runtime cannot run: %s", missing)
    except DomainUnavailableError as exc:
        log.warning("agent-domain not reachable at startup (%s); will retry", exc)

    yield


app = FastAPI(title="Notelite Agent Runtime", lifespan=lifespan)

app.include_router(router)
