import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.routes import catalog_service, playbook_service, router

from integrations.embedder import embeddings_available
from integrations.reranker import reranker_available


log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # A catalog that contradicts itself is a deployment error, not a request
    # error: refuse to serve it rather than fail one runtime call at a time.
    problems = catalog_service.validate_catalog()
    if problems:
        raise RuntimeError("Invalid domain catalog:\n" + "\n".join(problems))

    # Ranking is served remotely, so there is no model to warm here. Just say
    # which paths are usable, so a misconfigured host is obvious at boot rather
    # than on the first search.
    log.info(
        "ranking: reranker=%s embeddings=%s",
        "on" if reranker_available() else "off",
        "on" if embeddings_available() else "off",
    )

    yield


app = FastAPI(title="Notelite Agent Domain", lifespan=lifespan)

app.include_router(router)
