"""Local training and evaluation, executed inside a hospital node."""

from __future__ import annotations

import zlib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import List, Optional, Tuple

from ml.common.datasets import load_local_dataset
from ml.common.types import ArrayDataset, EvalResult, TrainConfig, Weights
from ml.ehr.features import EHR_REFERENCE_SCALE
from ml.ehr.imputation import MissingnessConfig, impute_splits
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
    #: EHR only: simulated gaps and imputation (counts only), or None.
    missing_values: Optional[dict] = field(default=None)


def load_training_splits(
    hospital_dir: Path, modality: str, missingness: Optional[MissingnessConfig] = None
) -> Tuple[ArrayDataset, ArrayDataset, Optional[dict]]:
    """This hospital's train and held-out splits, ready for the model.

    For EHR, gaps (real ones, or simulated with ``missingness``) are filled by KNN imputation fitted on the
    training split only; the held-out split is filled from training neighbours and never used to fit.
    """
    allow = modality == "ehr"
    train = load_local_dataset(hospital_dir, modality, "train", allow_missing_features=allow)
    val = load_local_dataset(hospital_dir, modality, "val", allow_missing_features=allow)
    if modality != "ehr":
        return train, val, None
    salt = zlib.crc32(str(Path(hospital_dir).resolve().name).encode())
    X_train, X_val, report = impute_splits(train.X, val.X, missingness, salt=salt, scale=EHR_REFERENCE_SCALE)
    # Only reported when there were gaps to fill; otherwise nothing extra leaves the node.
    return replace(train, X=X_train), replace(val, X=X_val), (report if report["imputation"] else None)


def train_on_local_data(
    hospital_dir: Path,
    modality: str,
    global_weights: Weights,
    config: TrainConfig,
    backend: Optional[str] = None,
    missingness: Optional[MissingnessConfig] = None,
) -> LocalTrainingOutput:
    """Start from the global weights and train on this hospital's own data."""
    adapter = get_adapter(modality, backend)
    train, validation, missing = load_training_splits(hospital_dir, modality, missingness)
    result = adapter.train_local(global_weights, train, config)
    local_metrics = metrics_from_evaluation(adapter.evaluate(result.weights, validation), adapter.task)
    return LocalTrainingOutput(
        weights=result.weights,
        num_samples=result.num_samples,
        history=result.history,
        duration_seconds=result.duration_seconds,
        local_validation=local_metrics,
        dataset_source=train.source,
        missing_values=missing,
    )


def evaluate_on_local_data(
    hospital_dir: Path,
    modality: str,
    weights: Weights,
    backend: Optional[str] = None,
    split: str = "val",
    missingness: Optional[MissingnessConfig] = None,
) -> EvalResult:
    """Score a model on this hospital's held-out split; returns sufficient statistics only."""
    adapter = get_adapter(modality, backend)
    train, validation, _ = load_training_splits(hospital_dir, modality, missingness)
    return adapter.evaluate(weights, train if split == "train" else validation)
