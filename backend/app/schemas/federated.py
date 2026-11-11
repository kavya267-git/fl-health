"""Federated-learning schemas."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.common import OpenModel

Modality = Literal["ehr", "ecg", "xray"]


class DifferentialPrivacyConfig(BaseModel):
    enabled: bool = False
    clip_norm: float = Field(default=1.0, gt=0, le=1000)
    noise_multiplier: float = Field(default=0.0, ge=0, le=100)
    delta: float = Field(default=1e-5, gt=0, lt=1)
    adaptive_clipping: bool = Field(
        default=False,
        description=(
            "Adaptive clip norm (Andrew et al., 2021): the clip norm tracks target_quantile of the hospitals' update "
            "norms, estimated from noised clipping bits. clip_norm is the starting value when no earlier adaptive "
            "round of this modality has finished."
        ),
    )
    target_quantile: float = Field(default=0.5, gt=0, lt=1)
    clip_learning_rate: float = Field(default=0.2, gt=0, le=5)
    quantile_budget_share: float = Field(default=0.1, gt=0, lt=1)


class StartRoundRequest(BaseModel):
    modality: Modality
    hospital_ids: Optional[List[str]] = Field(default=None, description="Defaults to every online hospital.")
    local_epochs: int = Field(default=2, ge=1, le=20)
    batch_size: int = Field(default=32, ge=2, le=512)
    learning_rate: float = Field(default=0.003, gt=0, le=1)
    min_participants: int = Field(default=2, ge=1, le=16)
    auto_aggregate: bool = True
    differential_privacy: DifferentialPrivacyConfig = Field(default_factory=DifferentialPrivacyConfig)
    simulated_missing_rate: float = Field(
        default=0.0,
        ge=0,
        le=0.5,
        description=(
            "EHR only. Share of feature values each hospital blanks completely at random before training, to "
            "exercise KNN imputation (fitted on its own training split). 0 = off."
        ),
    )
    deadline_seconds: int = Field(
        default=600,
        ge=10,
        le=86400,
        description="Hospitals with no update (or, later, no evaluation) after this long are dropped.",
    )


class HeartbeatRequest(BaseModel):
    """What a node reports about itself: software and machine facts, and record counts only."""

    hospital_id: str
    hostname: Optional[str] = Field(default=None, max_length=120)
    ml_backend: Optional[str] = Field(default=None, max_length=40)
    device: Optional[str] = Field(default=None, max_length=40)
    software_version: Optional[str] = Field(default=None, max_length=40)
    architectures: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    data_summary: Dict[str, Any] = Field(default_factory=dict)


class DataCheckReport(BaseModel):
    """Per modality: passed, train_records, val_records, label_counts, problems. Counts and notes only."""

    hospital_id: str
    modalities: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


class HeartbeatAccepted(BaseModel):
    hospital_id: str
    received_at: str
    timeout_seconds: int
    #: The operator's switch; a node that is off declines any round it was invited to.
    participating: bool = True


class Participant(OpenModel):
    hospital_id: str
    hospital_name: Optional[str] = None
    status: str
    num_samples: Optional[int] = None
    error: Optional[str] = None
    joined_at: Optional[str] = None
    update_received_at: Optional[str] = None
    evaluated_at: Optional[str] = None
    local_metrics: Optional[Dict[str, Any]] = None


class Round(OpenModel):
    id: str
    round_number: int
    modality: Modality
    status: str
    config: Dict[str, Any]
    base_model_version: int
    result_model_version: Optional[int] = None
    num_participants: int
    aggregation_status: str
    global_metrics: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_by: Optional[str] = None
    is_simulated: bool
    started_at: str
    ended_at: Optional[str] = None


class RoundDetail(Round):
    participants: List[Participant]
    updates_received: int
    updates_expected: int
    evaluations_received: int


class ParticipateRequest(BaseModel):
    hospital_id: str = Field(min_length=1, max_length=64)
    data_summary: Optional[Dict[str, Any]] = None


class NodeRoundInfo(OpenModel):
    round_id: str
    modality: Modality
    status: str
    training: Dict[str, Any]
    differential_privacy: Dict[str, Any]
    model: Dict[str, Any]


class NodePendingRounds(BaseModel):
    hospital_id: str
    round_ids: List[str]
    #: False when the operator has switched participation off: the node declines these rounds.
    participating: bool = True


class UpdateAccepted(BaseModel):
    round_id: str
    hospital_id: str
    status: str
    weights_sha256: str
    update_norm: float


class EvaluationRequest(BaseModel):
    hospital_id: str = Field(min_length=1, max_length=64)
    evaluation: Dict[str, Any]
    explanation: Optional[Dict[str, Any]] = None


class EvaluationAccepted(BaseModel):
    round_id: str
    hospital_id: str
    status: str


class FailureRequest(BaseModel):
    hospital_id: str = Field(min_length=1, max_length=64)
    stage: str = Field(min_length=1, max_length=40)
    message: str = Field(max_length=500)


class FinalizeRequest(BaseModel):
    allow_partial: bool = True


class RoundMetrics(BaseModel):
    round_id: str
    modality: Modality
    status: str
    global_metrics: Optional[Dict[str, Any]] = None
    local: List[Dict[str, Any]]
    global_per_hospital: List[Dict[str, Any]]
