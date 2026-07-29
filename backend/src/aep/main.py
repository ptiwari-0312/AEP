"""Composition root: wires all modules into one FastAPI app
(docs/architecture/02-repo-design.md §2)."""

from __future__ import annotations

from fastapi import FastAPI

from .core.errors import register_exception_handlers
from .modules.auth import router as auth_router
from .modules.context_builder import router as context_builder_router
from .modules.projects import router as projects_router
from .modules.task_memory import router as task_memory_router


def create_app() -> FastAPI:
    app = FastAPI(title="AEP", version="0.1.0")
    register_exception_handlers(app)
    app.include_router(auth_router)
    app.include_router(projects_router)
    app.include_router(task_memory_router)
    app.include_router(context_builder_router)

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
