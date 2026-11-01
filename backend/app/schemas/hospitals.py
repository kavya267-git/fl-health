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
    #: The operator's "Take part in future rounds" switch. Off: never invited, and the node declines.
    participating: bool = True
    #: External nodes only: the latest heartbeat. None if the node has never connected.
    node: Optional[NodePresence] = None


class HospitalMetrics(BaseModel):
    hospital_id: str
    local_training: List[Dict[str, Any]]
    local_validation: List[Dict[str, Any]]
    global_model_on_local_data: List[Dict[str, Any]]
    participation: List[Dict[str, Any]]


class MyRound(OpenModel):
    """One round seen from a single hospital's side."""

    round_id: str
    round_number: int
    modality: str
    round_status: str
    status: str
    error: Optional[str] = None
    started_at: str
    joined_at: Optional[str] = None
    update_received_at: Optional[str] = None
    evaluated_at: Optional[str] = None
    num_samples: Optional[int] = None
    update_bytes: Optional[int] = None
    local_model: Optional[Dict[str, Any]] = None
    global_model_on_local_data: Optional[Dict[str, Any]] = None


class MyHospital(BaseModel):
    hospital: Hospital
    metrics: HospitalMetrics
    latest_round: Optional[MyRound] = None


class AvailabilityRequest(BaseModel):
    online: bool


class ParticipationRequest(BaseModel):
    participating: bool
