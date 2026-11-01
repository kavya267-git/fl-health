"""Shared FastAPI dependencies: service context, signed-in user, role and node checks."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import Depends, Request

from app.services.auth_service import require_role
from app.services.context import AppContext
from app.utils.errors import AuthenticationFailed, PermissionDenied


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


def bearer_token(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthenticationFailed("Sign in to continue.")
    return token.strip()


def current_user(token: str = Depends(bearer_token), ctx: AppContext = Depends(get_ctx)) -> Dict[str, Any]:
    return ctx.auth.authenticate(token)


def coordinator_user(user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    """Admins and FL coordinators may change state (start rounds, aggregate, ...)."""
    require_role(user, ("admin", "coordinator"))
    return user


def admin_user(user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    """Only administrators manage users and roles."""
    require_role(user, ("admin",))
    return user


def verify_node(request: Request, ctx: AppContext, hospital_id: str) -> None:
    """Hospital-node endpoints are authenticated with the node's own token."""
    token = request.headers.get("x-hospital-token", "")
    if not ctx.hospitals.verify_node_token(hospital_id, token):
        raise PermissionDenied("A valid X-Hospital-Token for this hospital is required.")
