"""Health and public configuration."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.routers.deps import get_ctx
from app.schemas.common import HealthResponse
from app.schemas.system import SystemConfig
from app.services.context import AppContext
from app.utils.time import utc_now_iso

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health", response_model=HealthResponse)
def health(ctx: AppContext = Depends(get_ctx)):
    ctx.db.fetch_one("SELECT COUNT(*) AS n FROM hospitals")
    return {
        "status": "ok",
        "version": ctx.settings.app_version,
        "demo_mode": ctx.settings.demo_mode,
        "database": "sqlite" if ctx.settings.is_sqlite else "postgresql",
        "time": utc_now_iso(),
    }


@router.get("/system/config", response_model=SystemConfig)
def system_config(ctx: AppContext = Depends(get_ctx)):
    """What the sign-in page needs to know: mode, auth provider, active model backends."""
    return ctx.system_config()
