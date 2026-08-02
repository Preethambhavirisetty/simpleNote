import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.routes import catalog_service, playbook_service, router

from integrations.embedder import embeddings_available, get_embedder


log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # A catalog that contradicts itself is a deployment error, not a request
    # error: refuse to serve it rather than fail one runtime call at a time.
    problems = catalog_service.validate_catalog()
    if problems:
        raise RuntimeError("Invalid domain catalog:\n" + "\n".join(problems))

    # Embeddings are optional: below the candidate limit nothing is embedded,
    # so a deployment without them is valid. Warm them only when present.
    if embeddings_available():
        get_embedder()
        playbook_service.initialize_embeddings()
    else:
        log.info("sentence-transformers not installed; semantic search disabled")

    yield


app = FastAPI(title="Notelite Agent Domain", lifespan=lifespan)

app.include_router(router)
