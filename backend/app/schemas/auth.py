"""Authentication schemas."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class DemoLoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)
    display_name: Optional[str] = Field(default=None, max_length=80)


class RoleChangeRequest(BaseModel):
    role: str = Field(min_length=1, max_length=32)


class User(BaseModel):
    id: str
    email: str
    display_name: Optional[str] = None
    role: str
    hospital_id: Optional[str] = None
    provider: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str
    expires_in: int
    user: User


class SessionResponse(BaseModel):
    recorded: bool
    user: User


class ManagedUser(BaseModel):
    """A user as shown to an administrator."""

    id: str
    email: str
    display_name: Optional[str] = None
    role: str
    hospital_id: Optional[str] = None
    created_at: str
    last_login_at: Optional[str] = None
    built_in: bool
    role_locked: bool
    role_locked_reason: Optional[str] = None
