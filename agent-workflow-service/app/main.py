from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.agent_workflow.checkpointing import close_shared_checkpointers
from app.agent_workflow.deadlines import shutdown_deadline_executor
from app.api.api_response import ApiResponse
from app.api.checkpointer import close_runtime_checkpointer
from app.api.config import SERVICE_PORT
from app.api.routes import router as agent_workflow_router
from app.api.action_controller import router as agent_workflow_action_router


log = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        yield
    finally:
        close_runtime_checkpointer()
        close_shared_checkpointers()
        shutdown_deadline_executor()


app = FastAPI(
    title="Agent Workflow Service",
    version="1.0.0",
    description="Standalone HTTP runtime for planner/executor/reviewer agent workflows.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=ApiResponse.fail(str(exc.detail)).model_dump(),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = "; ".join(
        f"{' → '.join(str(loc) for loc in err['loc'])}: {err['msg']}"
        for err in exc.errors()
    )
    return JSONResponse(
        status_code=422,
        content=ApiResponse.fail(f"Validation error: {errors}").model_dump(),
    )


@app.get("/health", response_model=ApiResponse[dict])
def health():
    return ApiResponse.ok({"status": "ok", "service": "agent-workflow", "port": SERVICE_PORT})


app.include_router(agent_workflow_router)
app.include_router(agent_workflow_action_router)
