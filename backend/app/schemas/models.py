"""Model-registry schemas."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from app.schemas.common import OpenModel


class TaskInfo(BaseModel):
    name: str
    description: str
    task_type: str
    class_names: List[str]
    primary_metric: str
    metric_definitions: Dict[str, str]


class ModelSummary(OpenModel):
    id: str
    modality: str
    architecture: str
    target_architecture: str
    backend: str
    is_target_architecture: bool
    summary: str
    task: TaskInfo
    num_parameters: int
    current_version: int
    training_status: str
    latest_round_id: Optional[str] = None
    latest_metrics: Optional[Dict[str, Any]] = None
    dataset: Optional[Dict[str, Any]] = None
    last_updated: str
    trained_versions: int
    is_simulated: bool


class ModelVersion(OpenModel):
    version: int
    status: str
    architecture: str
    backend: str
    round_id: Optional[str] = None
    created_at: str
    weights_sha256: str
    weights_available: bool
    metrics: Optional[Dict[str, Any]] = None


class ModelDetail(ModelSummary):
    architecture_signature: str
    versions: List[ModelVersion]


class MetricPoint(OpenModel):
    version: int
    round_id: Optional[str] = None
    round_number: Optional[int] = None
    accuracy: float
    precision: float
    recall: float
    f1: float
    loss: float
    num_samples: int
    created_at: str


class ModelMetrics(OpenModel):
    model_id: str
    architecture: str
    backend: str
    task: TaskInfo
    dataset: Optional[Dict[str, Any]] = None
    series: List[MetricPoint]
    local_training: List[Dict[str, Any]]
    latest: Optional[Dict[str, Any]] = None
    is_simulated: bool
