from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.routes import catalog_service, playbook_service, router

from integrations.embedder import get_embedder


@asynccontextmanager
async def lifespan(app: FastAPI):
    # A catalog that contradicts itself is a deployment error, not a request
    # error: refuse to serve it rather than fail one runtime call at a time.
    problems = catalog_service.validate_catalog()
    if problems:
        raise RuntimeError("Invalid domain catalog:\n" + "\n".join(problems))

    get_embedder()
    playbook_service.initialize_embeddings()

    yield


app = FastAPI(title="Notelite Agent Domain", lifespan=lifespan)

app.include_router(router)
