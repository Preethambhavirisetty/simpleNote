from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.routes import playbook_service, router

from integrations.embedder import get_embedder


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_embedder()
    playbook_service.initialize_embeddings()

    yield


app = FastAPI(lifespan=lifespan)

app.include_router(router)