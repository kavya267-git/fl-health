"""Shared FastAPI dependencies: service context, signed-in user, role and node checks."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import Depends, Request

from app.services.auth_service import require_role
from app.services.context import AppContext
from app.services.permissions import HOSPITAL_ROLES, ensure_hospital_scope, require_permission
from app.utils.errors import AuthenticationFailed, PermissionDenied


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


def client_key(request: Request, ctx: AppContext) -> str:
    """The client's address, for rate limits. Behind a trusted proxy or tunnel (TRUST_PROXY_HEADERS), the first
    X-Forwarded-For entry; otherwise the socket peer."""
    if ctx.settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if forwarded:
            return forwarded[:64]
    return request.client.host if request.client else "unknown"


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


def permitted(permission: str):
    """Dependency: the signed-in user, if their role has ``permission`` (see app/services/permissions.py)."""

    def dependency(user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
        require_permission(user, permission)
        return user

    dependency.__name__ = f"permitted_{permission}"
    return dependency


def audit_reader(user: Dict[str, Any] = Depends(permitted("audit_read"))) -> Dict[str, Any]:
    """Who may read the audit log."""
    return user


def admin_user(user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    """Only administrators manage users and roles."""
    require_role(user, ("admin",))
    return user


def is_hospital_operator(user: Dict[str, Any]) -> bool:
    """Acts for one hospital (operator or manager): sees only that hospital's own per-hospital results."""
    return user.get("role") in HOSPITAL_ROLES


def ensure_hospital_access(user: Dict[str, Any], hospital_id: str) -> None:
    """Hospital operators and managers may open detailed pages only for their own hospital."""
    ensure_hospital_scope(user, hospital_id)


def hospital_operator(user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    """A signed-in hospital operator or manager who is linked to a hospital."""
    require_role(user, HOSPITAL_ROLES)
    if not user.get("hospital_id"):
        raise PermissionDenied("Your account is not linked to a hospital yet. Ask an administrator.")
    return user


def verify_node(request: Request, ctx: AppContext, hospital_id: str) -> None:
    """Hospital-node endpoints are authenticated with the node's own token."""
    token = request.headers.get("x-hospital-token", "")
    if not ctx.hospitals.verify_node_token(hospital_id, token):
        raise PermissionDenied("A valid X-Hospital-Token for this hospital is required.")
