"""Shared data structures for datasets, tasks, training and evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

# A model's parameters as a flat mapping of tensor name -> NumPy array. This is
# the only representation that crosses the hospital/coordinator boundary, so
# the coordinator never needs a deep-learning framework to aggregate.
Weights = Dict[str, np.ndarray]

MODALITIES = ("ehr", "ecg", "xray")


@dataclass
class ArrayDataset:
    """An in-memory dataset split that lives inside one hospital node."""

    X: np.ndarray
    y: np.ndarray
    modality: str
    split: str
    source: str  # "simulated", "mimic-iv", "mit-bih", "nih-chestxray14", ...
    feature_names: Optional[List[str]] = None
    description: str = ""

    def __len__(self) -> int:
        return int(self.y.shape[0])

    @property
    def is_simulated(self) -> bool:
        return self.source == "simulated"


@dataclass(frozen=True)
class TaskSpec:
    """What a modality's model predicts and how it is scored."""

    modality: str
    name: str
    description: str
    task_type: str  # "binary" | "multiclass"
    class_names: tuple
    primary_metric: str
    metric_definitions: Dict[str, str]

    @property
    def num_classes(self) -> int:
        return len(self.class_names)


CLASS_WEIGHTINGS = ("none", "balanced")


@dataclass
class TrainConfig:
    local_epochs: int = 1
    batch_size: int = 32
    learning_rate: float = 1e-3
    seed: int = 0
    #: "none": plain cross-entropy (the platform default). "balanced": each class
    #: weighted by n / (num_classes * n_class), counted on the hospital's own
    #: training split. An explicit option, never switched on implicitly.
    class_weighting: str = "none"
    #: FedProx proximal term mu/2 * ||w - w_global||^2 (Li et al., 2020). 0 = FedAvg.
    proximal_mu: float = 0.0

    def validate(self) -> None:
        if self.local_epochs < 1 or self.local_epochs > 50:
            raise ValueError("local_epochs must be between 1 and 50")
        if self.batch_size < 2 or self.batch_size > 1024:
            raise ValueError("batch_size must be between 2 and 1024")
        if not (0 < self.learning_rate <= 1.0):
            raise ValueError("learning_rate must be in (0, 1]")
        if self.class_weighting not in CLASS_WEIGHTINGS:
            raise ValueError(f"class_weighting must be one of {CLASS_WEIGHTINGS}")
        if self.proximal_mu < 0:
            raise ValueError("proximal_mu must be non-negative")


@dataclass
class TrainResult:
    weights: Weights
    num_samples: int
    history: List[dict] = field(default_factory=list)  # one entry per local epoch
    duration_seconds: float = 0.0


@dataclass
class EvalResult:
    """Sufficient statistics of an evaluation.

    A confusion matrix (rows = true class, columns = predicted class) plus the
    summed loss lets the coordinator pool evaluations from several hospitals
    exactly, without seeing a single prediction or record.
    """

    confusion: np.ndarray
    loss_sum: float
    num_samples: int

    def to_dict(self) -> dict:
        return {
            "confusion": np.asarray(self.confusion).astype(int).tolist(),
            "loss_sum": float(self.loss_sum),
            "num_samples": int(self.num_samples),
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "EvalResult":
        return cls(
            confusion=np.asarray(payload["confusion"], dtype=np.int64),
            loss_sum=float(payload["loss_sum"]),
            num_samples=int(payload["num_samples"]),
        )
