"""The interface every modality model implements.

The federated layer only ever calls these methods, so a model backend can be
swapped without touching the coordinator. Weights cross the boundary as plain
NumPy arrays (see ``ml.common.weights``).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np

from ml.common.types import ArrayDataset, EvalResult, TaskSpec, TrainConfig, TrainResult, Weights
from ml.common.weights import architecture_signature, count_parameters
from ml.evaluation.metrics import evaluate_probabilities


class ModelAdapter(ABC):
    #: "ehr" | "ecg" | "xray"
    modality: str = ""
    #: Human-readable architecture name, e.g. "TabNet".
    architecture: str = ""
    #: "pytorch" or "numpy-reference".
    backend: str = ""
    #: Longer description shown in the model registry.
    summary: str = ""

    def __init__(self, task: TaskSpec):
        self.task = task

    # ------------------------------------------------------------------ core
    @abstractmethod
    def init_weights(self, seed: int = 0) -> Weights:
        """Freshly initialised weights (global model version 0)."""

    @abstractmethod
    def train_local(self, weights: Weights, dataset: ArrayDataset, config: TrainConfig) -> TrainResult:
        """Train on one hospital's local data, starting from the global weights."""

    @abstractmethod
    def predict_proba(self, weights: Weights, X: np.ndarray) -> np.ndarray:
        """Class probabilities with shape [n_samples, n_classes] for raw inputs ``X``."""

    # --------------------------------------------------------------- derived
    def evaluate(self, weights: Weights, dataset: ArrayDataset) -> EvalResult:
        probabilities = self.predict_proba(weights, dataset.X)
        return evaluate_probabilities(probabilities, dataset.y)

    def reference_weights(self) -> Weights:
        """Weights with the right names and shapes; values are irrelevant."""
        return self.init_weights(0)

    def signature(self, weights: Weights | None = None) -> str:
        """Architecture signature. Cached when computed for the adapter itself."""
        label = f"{self.backend}:{self.architecture}"
        if weights is not None:
            return architecture_signature(weights, label)
        cached = getattr(self, "_signature_cache", None)
        if cached is None:
            reference = self.reference_weights()
            cached = (architecture_signature(reference, label), count_parameters(reference))
            self._signature_cache = cached
        return cached[0]

    @property
    def signature_label(self) -> str:
        return f"{self.backend}:{self.architecture}"

    def num_parameters(self) -> int:
        self.signature()
        return self._signature_cache[1]

    def task_dict(self) -> dict:
        return {
            "name": self.task.name,
            "description": self.task.description,
            "task_type": self.task.task_type,
            "class_names": list(self.task.class_names),
            "primary_metric": self.task.primary_metric,
            "metric_definitions": dict(self.task.metric_definitions),
        }

    def describe(self) -> dict:
        return {
            "modality": self.modality,
            "architecture": self.architecture,
            "backend": self.backend,
            "summary": self.summary,
            "num_parameters": self.num_parameters(),
            "architecture_signature": self.signature(),
            "task": self.task_dict(),
        }
