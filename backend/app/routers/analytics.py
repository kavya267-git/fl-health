"""Analytics endpoints: overview, surveillance hotspots, forecasts, explainability, privacy."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query

from app.routers.deps import get_ctx, permitted
from app.schemas.analytics import (
    AnalyticsOptions,
    ExplainabilityResponse,
    ForecastResponse,
    HotspotResponse,
    OverviewResponse,
    PrivacyReport,
)
from app.services.context import AppContext
from app.services.permissions import jurisdiction_of
from app.services.views import overview

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/overview", response_model=OverviewResponse)
def get_overview(user: Dict[str, Any] = Depends(permitted("dashboard_overview")), ctx: AppContext = Depends(get_ctx)):
    """Dashboard summary: KPIs, model status, rounds, surveillance and forecast highlights."""
    return overview(ctx, user)


@router.get("/options", response_model=AnalyticsOptions)
def get_options(user: Dict[str, Any] = Depends(permitted("surveillance_read")), ctx: AppContext = Depends(get_ctx)):
    """Diseases, regions and weeks available for the surveillance and forecast pages (a health officer's
    regions are limited to their jurisdiction)."""
    return ctx.surveillance.options(jurisdiction_of(user))


@router.get("/hotspots", response_model=HotspotResponse)
def get_hotspots(
    disease: Optional[str] = Query(default=None),
    period: Optional[str] = Query(default=None),
    user: Dict[str, Any] = Depends(permitted("surveillance_read")),
    ctx: AppContext = Depends(get_ctx),
):
    """Regional statistics and hotspot candidates for one disease and week, with GeoJSON (a health
    officer receives only the regions in their jurisdiction)."""
    return ctx.surveillance.hotspots(disease, period, user["email"], jurisdiction_of(user))


@router.get("/forecast", response_model=ForecastResponse)
def get_forecast(
    region_id: Optional[str] = Query(default=None),
    disease: Optional[str] = Query(default=None),
    horizon: int = Query(default=8, ge=1, le=26),
    user: Dict[str, Any] = Depends(permitted("surveillance_read")),
    ctx: AppContext = Depends(get_ctx),
):
    """Forecast of weekly cases for one region and disease, with validation metrics and intervals."""
    return ctx.forecasts.forecast(region_id, disease, horizon, user["email"], jurisdiction_of(user))


@router.get("/explainability", response_model=ExplainabilityResponse)
def get_explainability(
    modality: str = Query(default="ehr"),
    scope: str = Query(default="individual"),
    case_id: Optional[str] = Query(default=None),
    user: Dict[str, Any] = Depends(permitted("explainability_read")),
    ctx: AppContext = Depends(get_ctx),
):
    """Global or individual explanation for a modality's current global model."""
    return ctx.explainability.explain(modality, scope, case_id, user["email"])


@router.get("/privacy", response_model=PrivacyReport)
def get_privacy(user: Dict[str, Any] = Depends(permitted("explainability_read")), ctx: AppContext = Depends(get_ctx)):
    """Privacy configuration, validation checks and prototype DP accounting."""
    return ctx.privacy.report()
