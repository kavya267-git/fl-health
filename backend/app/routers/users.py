"""User management (administrators only)."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends

from app.routers.deps import admin_user, get_ctx
from app.schemas.auth import ManagedUser, RoleChangeRequest
from app.services.context import AppContext

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=List[ManagedUser])
def list_users(user: Dict[str, Any] = Depends(admin_user), ctx: AppContext = Depends(get_ctx)):
    """Everyone who has an account, with their role."""
    return ctx.auth.list_users()


@router.post("/{user_id}/role", response_model=ManagedUser)
def set_role(
    user_id: str,
    body: RoleChangeRequest,
    user: Dict[str, Any] = Depends(admin_user),
    ctx: AppContext = Depends(get_ctx),
):
    """Change another user's role. You cannot change your own."""
    return ctx.auth.set_role(user, user_id, body.role)
