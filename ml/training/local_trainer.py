"""Local training and evaluation, executed inside a hospital node."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from ml.common.datasets import load_local_dataset
from ml.common.types import EvalResult, TrainConfig, Weights
from ml.evaluation.metrics import metrics_from_evaluation
from ml.registry import get_adapter


@dataclass
class LocalTrainingOutput:
    weights: Weights
    num_samples: int
    history: List[dict]
    duration_seconds: float
    local_validation: dict  # metrics of the locally trained model on the local validation split
    dataset_source: str


def train_on_local_data(
    hospital_dir: Path,
    modality: str,
    global_weights: Weights,
    config: TrainConfig,
    backend: Optional[str] = None,
) -> LocalTrainingOutput:
    """Start from the global weights and train on this hospital's own data."""
    adapter = get_adapter(modality, backend)
    train = load_local_dataset(hospital_dir, modality, "train")
    result = adapter.train_local(global_weights, train, config)
    validation = load_local_dataset(hospital_dir, modality, "val")
    local_metrics = metrics_from_evaluation(adapter.evaluate(result.weights, validation), adapter.task)
    return LocalTrainingOutput(
        weights=result.weights,
        num_samples=result.num_samples,
        history=result.history,
        duration_seconds=result.duration_seconds,
        local_validation=local_metrics,
        dataset_source=train.source,
    )


def evaluate_on_local_data(
    hospital_dir: Path,
    modality: str,
    weights: Weights,
    backend: Optional[str] = None,
    split: str = "val",
) -> EvalResult:
    """Score a model on this hospital's held-out split; returns sufficient statistics only."""
    adapter = get_adapter(modality, backend)
    return adapter.evaluate(weights, load_local_dataset(hospital_dir, modality, split))
