"""Health officer views: situation report (and its exports) and alerts. Scoped to the officer's jurisdiction."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field

from app.routers.deps import get_ctx, permitted
from app.services.context import AppContext
from app.services.permissions import jurisdiction_of

router = APIRouter(tags=["health officer"])


class OutcomeRequest(BaseModel):
    outcome: str = Field(min_length=1, max_length=32)
    note: str = Field(min_length=1, max_length=1000)


def _filename(user: Dict[str, Any], ctx: AppContext, suffix: str) -> str:
    flag = "SIMULATED-" if ctx.surveillance.is_simulated() else ""
    return f"{flag}situation-report.{suffix}"


@router.get("/api/officer/situation")
def situation(user: Dict[str, Any] = Depends(permitted("situation_report")), ctx: AppContext = Depends(get_ctx)):
    """This week per disease and region, with status, usual level, completeness and the ensemble forecast."""
    return ctx.situation.situation(jurisdiction_of(user), user["email"])


@router.get("/api/officer/forecast-status")
def forecast_status(user: Dict[str, Any] = Depends(permitted("situation_report")), ctx: AppContext = Depends(get_ctx)):
    """About this forecast: weights, validation window, data date, or that it is still being computed."""
    return ctx.situation.about_forecast()


@router.get("/api/officer/situation.csv")
def situation_csv(user: Dict[str, Any] = Depends(permitted("situation_report")), ctx: AppContext = Depends(get_ctx)):
    body = ctx.situation.export_csv(jurisdiction_of(user), user["email"])
    return Response(
        body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{_filename(user, ctx, "csv")}"'},
    )


@router.get("/api/officer/situation.pdf")
def situation_pdf(user: Dict[str, Any] = Depends(permitted("situation_report")), ctx: AppContext = Depends(get_ctx)):
    body = ctx.situation.export_pdf(jurisdiction_of(user), user["email"])
    return Response(
        body,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{_filename(user, ctx, "pdf")}"'},
    )


@router.get("/api/alerts")
def list_alerts(
    state: Optional[str] = Query(default=None),
    user: Dict[str, Any] = Depends(permitted("alerts_read")),
    ctx: AppContext = Depends(get_ctx),
) -> List[Dict[str, Any]]:
    return ctx.alerts.list(jurisdiction_of(user), state)


@router.post("/api/alerts/{alert_id}/acknowledge")
def acknowledge(alert_id: int, user: Dict[str, Any] = Depends(permitted("alerts_manage")), ctx: AppContext = Depends(get_ctx)):
    return ctx.alerts.acknowledge(alert_id, user)


@router.post("/api/alerts/{alert_id}/outcome")
def record_outcome(
    alert_id: int,
    body: OutcomeRequest,
    user: Dict[str, Any] = Depends(permitted("alerts_manage")),
    ctx: AppContext = Depends(get_ctx),
):
    return ctx.alerts.record_outcome(alert_id, user, body.outcome, body.note)
