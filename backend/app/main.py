"""PrivaFuse coordinator API (FastAPI application)."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import Settings, load_settings
from app.database import DatabaseError
from app.federated.deadlines import DeadlineWatcher
from app.routers import analytics, audit, auth, federated, hospitals, models, my_hospital, system, users
from app.services.context import bootstrap, build_context
from app.utils.errors import ServiceError

logger = logging.getLogger("fl.api")

DESCRIPTION = """
Coordinator API for **PrivaFuse** - a multimodal federated-learning prototype.

Hospitals train EHR, ECG and X-ray models locally and send only model updates.
This API orchestrates rounds, aggregates compatible updates with FedAvg, keeps
the model registry, serves aggregated analytics and records an audit trail.
"""


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        ctx = build_context(settings)
        bootstrap(ctx)
        ctx.deadlines = DeadlineWatcher(ctx.coordinator)
        ctx.deadlines.start()
        app.state.ctx = ctx
        logger.info(
            "PrivaFuse ready (demo_mode=%s, auth=%s, nodes=%s)",
            settings.demo_mode,
            settings.auth_provider,
            settings.hospital_nodes,
        )
        try:
            yield
        finally:
            ctx.close()

    app = FastAPI(title="PrivaFuse API", version=settings.app_version, description=DESCRIPTION, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "X-Hospital-Token"],
    )

    @app.exception_handler(ServiceError)
    async def service_error_handler(request: Request, exc: ServiceError):
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message}, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        problems = []
        for error in exc.errors():
            location = ".".join(str(part) for part in error.get("loc", []) if part not in ("body", "query", "path"))
            problems.append(f"{location}: {error.get('msg')}" if location else str(error.get("msg")))
        return JSONResponse(status_code=422, content={"detail": "Invalid request - " + "; ".join(problems)})

    @app.exception_handler(DatabaseError)
    async def database_error_handler(request: Request, exc: DatabaseError):
        logger.exception("Database error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=503, content={"detail": "The database is unavailable. Try again shortly."})

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception):
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "The server hit an unexpected error."})

    for module in (system, auth, users, hospitals, my_hospital, federated, models, analytics, audit):
        app.include_router(module.router)

    @app.get("/", include_in_schema=False)
    def root():
        return {"name": settings.app_name, "docs": "/docs", "health": "/api/health"}

    return app


app = create_app()
