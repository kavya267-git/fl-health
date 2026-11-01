"""Hospital endpoints."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends

from app.routers.deps import coordinator_user, current_user, get_ctx
from app.schemas.hospitals import AvailabilityRequest, Hospital, HospitalMetrics
from app.services.context import AppContext

router = APIRouter(prefix="/api/hospitals", tags=["hospitals"])


@router.get("", response_model=List[Hospital])
def list_hospitals(user: Dict[str, Any] = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    return ctx.hospitals.list()


@router.get("/{hospital_id}", response_model=Hospital)
def get_hospital(hospital_id: str, user: Dict[str, Any] = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    return ctx.hospitals.get(hospital_id)


@router.get("/{hospital_id}/metrics", response_model=HospitalMetrics)
def hospital_metrics(
    hospital_id: str, user: Dict[str, Any] = Depends(current_user), ctx: AppContext = Depends(get_ctx)
):
    return ctx.hospitals.metrics(hospital_id)


@router.post("/{hospital_id}/availability", response_model=Hospital)
def set_availability(
    hospital_id: str,
    body: AvailabilityRequest,
    user: Dict[str, Any] = Depends(coordinator_user),
    ctx: AppContext = Depends(get_ctx),
):
    """Take a hospital node offline or bring it back (to demonstrate partial participation)."""
    return ctx.hospitals.set_online(hospital_id, body.online, user["email"])
