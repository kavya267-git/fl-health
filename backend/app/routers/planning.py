"""Hospital resource planning: capacity (managers, own hospital), assumptions (administrators), projection."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.routers.deps import get_ctx, permitted
from app.services.context import AppContext
from app.services.permissions import HOSPITAL_ROLES, ensure_hospital_scope
from app.utils.errors import ValidationFailed

router = APIRouter(prefix="/api/planning", tags=["resource planning"])


class CapacityRequest(BaseModel):
    total_beds: int = Field(ge=1, le=100_000)
    icu_beds: int = Field(ge=0, le=100_000)
    occupancy_percent: float = Field(ge=0, le=100)


class AssumptionsRequest(BaseModel):
    admission_rate: float = Field(ge=0, le=1)
    icu_share: float = Field(ge=0, le=1)
    length_of_stay_days: float = Field(gt=0, le=365)


def _hospital_for(user: Dict[str, Any], hospital_id: Optional[str]) -> str:
    """A manager always gets their own hospital; an administrator names one."""
    if user["role"] in HOSPITAL_ROLES:
        own = user.get("hospital_id")
        ensure_hospital_scope(user, hospital_id or own)
        return own
    if not hospital_id:
        raise ValidationFailed("Choose a hospital (hospital_id).")
    return hospital_id


@router.get("")
def projection(
    hospital_id: Optional[str] = Query(default=None),
    user: Dict[str, Any] = Depends(permitted("planning_read")),
    ctx: AppContext = Depends(get_ctx),
):
    """Capacity, assumptions and the bed projection for the next weeks (a planning estimate)."""
    return ctx.planning.projection(_hospital_for(user, hospital_id))


@router.get("/capacity/history")
def capacity_history(
    hospital_id: Optional[str] = Query(default=None),
    user: Dict[str, Any] = Depends(permitted("planning_read")),
    ctx: AppContext = Depends(get_ctx),
):
    return ctx.planning.capacity_history(_hospital_for(user, hospital_id))


@router.post("/capacity")
def set_capacity(body: CapacityRequest, user: Dict[str, Any] = Depends(permitted("capacity_write")), ctx: AppContext = Depends(get_ctx)):
    """A hospital manager records their own hospital's beds and current occupancy (kept with a timestamp)."""
    return ctx.planning.set_capacity(
        _hospital_for(user, None), body.total_beds, body.icu_beds, body.occupancy_percent, user["email"]
    )


@router.get("/assumptions")
def assumptions(user: Dict[str, Any] = Depends(permitted("planning_read")), ctx: AppContext = Depends(get_ctx)):
    return ctx.planning.assumptions()


@router.post("/assumptions/{disease}")
def set_assumptions(
    disease: str,
    body: AssumptionsRequest,
    user: Dict[str, Any] = Depends(permitted("assumptions_write")),
    ctx: AppContext = Depends(get_ctx),
):
    return ctx.planning.set_assumptions(disease, body.model_dump(), user["email"])
