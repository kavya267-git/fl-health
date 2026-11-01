"""System configuration schema (safe to expose before sign-in)."""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel

from app.schemas.common import ModelBackend


class DemoAccount(BaseModel):
    email: str
    role: str
    display_name: str
    hospital_id: Optional[str] = None


class SystemConfig(BaseModel):
    app_name: str
    version: str
    demo_mode: bool
    simulated_label: str
    auth_provider: str
    demo_accounts: List[DemoAccount]
    signup_enabled: bool
    hospital_nodes: str
    ml_backend: str
    database: str
    pytorch_available: bool
    model_backends: Dict[str, ModelBackend]
    modalities: List[str]
