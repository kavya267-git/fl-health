"""Audit-log endpoints (admins and coordinators only)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query

from app.routers.deps import coordinator_user, get_ctx
from app.schemas.audit import AuditPage, AuditVerification
from app.services.audit_service import ACTIONS
from app.services.context import AppContext

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("", response_model=AuditPage)
def list_audit(
    search: Optional[str] = Query(default=None, max_length=100),
    action: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    hospital_id: Optional[str] = Query(default=None),
    round_id: Optional[str] = Query(default=None),
    date_from: Optional[str] = Query(default=None, description="ISO date or timestamp"),
    date_to: Optional[str] = Query(default=None, description="ISO date or timestamp"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: Dict[str, Any] = Depends(coordinator_user),
    ctx: AppContext = Depends(get_ctx),
):
    page = ctx.audit.list_entries(search, action, status, hospital_id, round_id, date_from, date_to, limit, offset)
    return {**page, "limit": limit, "offset": offset, "actions": list(ACTIONS)}


@router.get("/verify", response_model=AuditVerification)
def verify_audit(user: Dict[str, Any] = Depends(coordinator_user), ctx: AppContext = Depends(get_ctx)):
    """Recompute the hash chain and report whether any entry was altered, removed or reordered."""
    result = ctx.audit.verify_chain()
    return {
        **result,
        "note": (
            "A valid chain means no stored entry was altered, removed or reordered since it was written. "
            "It does not make the database immutable: someone able to rewrite every entry could rebuild the chain."
        ),
    }
