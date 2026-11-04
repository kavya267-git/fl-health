"""Hospital endpoints."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends

from app.routers.deps import ensure_hospital_access, get_ctx, is_hospital_operator, permitted
from app.schemas.hospitals import AvailabilityRequest, Hospital, HospitalMetrics, ParticipationRequest
from app.services.context import AppContext

router = APIRouter(prefix="/api/hospitals", tags=["hospitals"])


@router.get("", response_model=List[Hospital])
def list_hospitals(user: Dict[str, Any] = Depends(permitted("hospitals_list")), ctx: AppContext = Depends(get_ctx)):
    return ctx.hospitals.list()


@router.get("/{hospital_id}", response_model=Hospital)
def get_hospital(hospital_id: str, user: Dict[str, Any] = Depends(permitted("hospital_detail")), ctx: AppContext = Depends(get_ctx)):
    ensure_hospital_access(user, hospital_id)
    return ctx.hospitals.get(hospital_id)


@router.get("/{hospital_id}/metrics", response_model=HospitalMetrics)
def hospital_metrics(
    hospital_id: str, user: Dict[str, Any] = Depends(permitted("hospital_detail")), ctx: AppContext = Depends(get_ctx)
):
    ensure_hospital_access(user, hospital_id)
    return ctx.hospitals.metrics(hospital_id)


@router.post("/{hospital_id}/availability", response_model=Hospital)
def set_availability(
    hospital_id: str,
    body: AvailabilityRequest,
    user: Dict[str, Any] = Depends(permitted("hospital_availability")),
    ctx: AppContext = Depends(get_ctx),
):
    """Take a hospital node offline or bring it back (to demonstrate partial participation)."""
    return ctx.hospitals.set_online(hospital_id, body.online, user["email"])


@router.post("/{hospital_id}/participation", response_model=Hospital)
def set_participation(
    hospital_id: str,
    body: ParticipationRequest,
    user: Dict[str, Any] = Depends(permitted("hospital_participation")),
    ctx: AppContext = Depends(get_ctx),
):
    """"Take part in future rounds": the hospital's own operator, or an administrator or coordinator."""
    if is_hospital_operator(user):
        ensure_hospital_access(user, hospital_id)
    return ctx.hospitals.set_participation(hospital_id, body.participating, user["email"])
