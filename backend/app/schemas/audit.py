"""Audit-log schemas."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class AuditEntry(BaseModel):
    id: int
    timestamp: str
    actor: str
    action: str
    hospital_id: Optional[str] = None
    round_id: Optional[str] = None
    model_version: Optional[str] = None
    status: str
    details: Optional[Dict[str, Any]] = None
    previous_hash: str
    current_hash: str


class AuditPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[AuditEntry]
    actions: List[str]


class AuditVerification(BaseModel):
    valid: bool
    entries_checked: int
    first_invalid_id: Optional[int] = None
    reason: Optional[str] = None
    latest_hash: Optional[str] = None
    note: str
