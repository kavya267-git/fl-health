"""Hospital registration: the public form (no sign-in) and the administrator's review queue."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from app.routers.deps import get_ctx, permitted
from app.services.context import AppContext

router = APIRouter(prefix="/api/registrations", tags=["hospital registration"])


class RegistrationRequest(BaseModel):
    """Organisation and contact details only. There is no field (and no upload) for patient data."""

    model_config = {"extra": "forbid"}

    hospital_name: str = Field(max_length=200)
    region_id: str = Field(max_length=64)
    contact_name: str = Field(max_length=200)
    contact_email: str = Field(max_length=300)
    password: str = Field(max_length=256)
    password_confirm: str = Field(max_length=256)
    modalities: List[str] = Field(max_length=3)
    approx_record_counts: Dict[str, int] = Field(default_factory=dict)
    confirm_no_patient_data: bool = False


class ReasonRequest(BaseModel):
    reason: str = Field(max_length=500)


def client_key(request: Request, ctx: AppContext) -> str:
    """The client's address for rate limiting. Behind a trusted proxy (TRUST_PROXY_HEADERS), the first
    X-Forwarded-For entry; otherwise the socket peer."""
    if ctx.settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if forwarded:
            return forwarded[:64]
    return request.client.host if request.client else "unknown"


@router.get("/regions")
def regions(ctx: AppContext = Depends(get_ctx)) -> List[Dict[str, str]]:
    """Region ids and names for the form (no counts, no other data)."""
    return ctx.registrations.regions()


@router.post("", status_code=201)
def submit(body: RegistrationRequest, request: Request, ctx: AppContext = Depends(get_ctx)) -> Dict[str, Any]:
    """Register a hospital. No sign-in. The operator account is created disabled until an administrator approves."""
    return ctx.registrations.submit(body.model_dump(), client_key(request, ctx))


@router.get("")
def list_registrations(
    status: Optional[str] = Query(default=None),
    user: Dict[str, Any] = Depends(permitted("registrations_manage")),
    ctx: AppContext = Depends(get_ctx),
) -> List[Dict[str, Any]]:
    return ctx.registrations.list(status)


@router.get("/pending-count")
def pending_count(
    user: Dict[str, Any] = Depends(permitted("registrations_manage")), ctx: AppContext = Depends(get_ctx)
) -> Dict[str, int]:
    return {"pending": ctx.registrations.pending_count()}


@router.post("/{registration_id}/approve")
def approve(
    registration_id: str,
    user: Dict[str, Any] = Depends(permitted("registrations_manage")),
    ctx: AppContext = Depends(get_ctx),
) -> Dict[str, Any]:
    return ctx.registrations.approve(registration_id, user)


@router.post("/{registration_id}/reject")
def reject(
    registration_id: str,
    body: ReasonRequest,
    user: Dict[str, Any] = Depends(permitted("registrations_manage")),
    ctx: AppContext = Depends(get_ctx),
) -> Dict[str, Any]:
    return ctx.registrations.reject(registration_id, body.reason, user)


@router.post("/{registration_id}/revoke")
def revoke(
    registration_id: str,
    body: ReasonRequest,
    user: Dict[str, Any] = Depends(permitted("registrations_manage")),
    ctx: AppContext = Depends(get_ctx),
) -> Dict[str, Any]:
    return ctx.registrations.revoke(registration_id, body.reason, user)
