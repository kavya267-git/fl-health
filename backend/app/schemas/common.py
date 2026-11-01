"""Shared schema pieces."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict


class OpenModel(BaseModel):
    """Response model that documents its key fields but keeps any extra ones.

    Analytics payloads carry nested, method-specific detail; declaring every
    leaf would add noise without adding safety.
    """

    model_config = ConfigDict(extra="allow")


class DataStatus(OpenModel):
    simulated: bool
    label: str


class ErrorResponse(BaseModel):
    detail: str


class HealthResponse(BaseModel):
    status: str
    version: str
    demo_mode: bool
    database: str
    time: str


class ModelBackend(OpenModel):
    architecture: Optional[str] = None
    backend: Optional[str] = None
    target_architecture: str
    is_target_architecture: bool
    architecture_signature: Optional[str] = None
