"""Hospital schemas. Only metadata and counts - never patient-level data."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from app.schemas.common import OpenModel


class ModalityDataSummary(OpenModel):
    source: str
    simulated: bool
    train_samples: int
    val_samples: int


class HospitalRound(OpenModel):
    id: str
    modality: str
    status: str
    participant_status: Optional[str] = None


class HospitalUpdate(OpenModel):
    round_id: str
    modality: str
    status: str
    num_samples: Optional[int] = None
    received_at: str


class NodePresence(OpenModel):
    connected: bool
    last_seen_at: Optional[str] = None
    connected_since: Optional[str] = None
    hostname: Optional[str] = None
    ml_backend: Optional[str] = None
    device: Optional[str] = None
    software_version: Optional[str] = None


class Hospital(BaseModel):
    id: str
    name: str
    kind: Optional[str] = None
    online: bool
    modalities: List[str]
    data_summary: Dict[str, ModalityDataSummary]
    is_simulated: bool
    last_activity_at: Optional[str] = None
    current_round: Optional[HospitalRound] = None
    latest_update: Optional[HospitalUpdate] = None
    rounds_completed: int
    fl_participation: str
    #: "in-process" (simulated inside the API) or "external" (a node on its own machine).
    node_mode: str = "in-process"
    #: External nodes only: the latest heartbeat. None if the node has never connected.
    node: Optional[NodePresence] = None


class HospitalMetrics(BaseModel):
    hospital_id: str
    local_training: List[Dict[str, Any]]
    local_validation: List[Dict[str, Any]]
    global_model_on_local_data: List[Dict[str, Any]]
    participation: List[Dict[str, Any]]


class AvailabilityRequest(BaseModel):
    online: bool
