"""Authentication endpoints."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, Request

from app.routers.deps import client_key, current_user, get_ctx
from app.schemas.auth import DemoLoginRequest, LoginResponse, RegisterRequest, SessionResponse, User
from app.services.context import AppContext

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/me", response_model=User)
def me(user: Dict[str, Any] = Depends(current_user)):
    """The signed-in user and their role."""
    return user


@router.post("/session", response_model=SessionResponse)
def record_session(user: Dict[str, Any] = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    """Called once by the client after a Supabase sign-in so the login is audited."""
    ctx.auth.record_login(user)
    return {"recorded": True, "user": user}


@router.post("/demo-login", response_model=LoginResponse)
def demo_login(body: DemoLoginRequest, request: Request, ctx: AppContext = Depends(get_ctx)):
    """Sign in with a built-in demo account or one created through sign-up.

    Only available when Supabase is not configured. Rate-limited per client address and per account (429).
    """
    return ctx.auth.demo_login(body.email, body.password, client_key(request, ctx))


@router.post("/register", response_model=LoginResponse)
def register(body: RegisterRequest, ctx: AppContext = Depends(get_ctx)):
    """Create an account and sign it in. The new account is always a viewer (read-only).

    Only available when Supabase is not configured and ALLOW_SIGNUP is on. With
    Supabase, the web app signs up through Supabase Auth instead.
    """
    return ctx.auth.register(body.email, body.password, body.display_name)
