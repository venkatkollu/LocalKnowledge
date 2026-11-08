"""Local KnowledgeOS API entry point.

This module only assembles the application: configuration, lifespan, CORS and
the HTTP routers. Business logic lives in the feature modules under
``backend/`` and the endpoint layer in ``backend/api/``.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import chat, documents, evaluations, indexes, models, system
from .config import APP_VERSION
from .db import init_db
from .runtime import EXECUTOR


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    try:
        yield
    finally:
        EXECUTOR.shutdown(wait=False, cancel_futures=False)


app = FastAPI(title="Local KnowledgeOS API", version=APP_VERSION, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv(
            "KNOWLEDGEOS_CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173",
        ).split(",")
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
)

for router_module in (system, models, documents, indexes, evaluations, chat):
    app.include_router(router_module.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=True)
