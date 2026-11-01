"""NumPy reference models.

These are *not* the project's target architectures (TabNet, CNN-BiLSTM,
EfficientNet-B3 - see ``ml/ehr``, ``ml/ecg``, ``ml/xray``). They are a small
multilayer perceptron per modality, trained with real gradient descent, that
lets the whole federated workflow run on a machine without PyTorch.

Whenever one of these is in use the model registry, the API and the UI say so
explicitly ("NumPy reference MLP"), so results are never attributed to an
architecture that did not produce them.
"""

from __future__ import annotations

import time
from typing import Callable

import numpy as np

from ml.common.adapter import ModelAdapter
from ml.common.tasks import get_task
from ml.common.types import ArrayDataset, TrainConfig, TrainResult, Weights
from ml.ecg.preprocess import ECG_BEAT_LENGTH, prepare_ecg
from ml.ehr.features import NUM_EHR_FEATURES, standardize_ehr
from ml.xray.preprocess import block_downsample, prepare_xray

_XRAY_REFERENCE_SIZE = 16


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - logits.max(axis=1, keepdims=True)
    exp = np.exp(shifted)
    return exp / exp.sum(axis=1, keepdims=True)


class NumpyMLPAdapter(ModelAdapter):
    backend = "numpy-reference"
    architecture = "NumPy reference MLP"

    def __init__(self, modality: str, input_dim: int, hidden: int, prepare: Callable[[np.ndarray], np.ndarray]):
        super().__init__(get_task(modality))
        self.modality = modality
        self.input_dim = input_dim
        self.hidden = hidden
        self._prepare = prepare
        self.summary = (
            f"One-hidden-layer perceptron ({input_dim} -> {hidden} -> {self.task.num_classes}) "
            "implemented in NumPy. Stand-in used because PyTorch is not installed or "
            "ML_BACKEND=numpy-reference."
        )

    # ------------------------------------------------------------- weights
    def init_weights(self, seed: int = 0) -> Weights:
        rng = np.random.default_rng(seed)
        classes = self.task.num_classes
        return {
            "W1": (rng.standard_normal((self.input_dim, self.hidden)) * np.sqrt(2.0 / self.input_dim)).astype(
                np.float32
            ),
            "b1": np.zeros(self.hidden, dtype=np.float32),
            "W2": (rng.standard_normal((self.hidden, classes)) * np.sqrt(1.0 / self.hidden)).astype(np.float32),
            "b2": np.zeros(classes, dtype=np.float32),
        }

    # ------------------------------------------------------------- forward
    @staticmethod
    def _forward(weights: Weights, features: np.ndarray):
        hidden_pre = features @ weights["W1"] + weights["b1"]
        hidden = np.maximum(hidden_pre, 0.0)
        logits = hidden @ weights["W2"] + weights["b2"]
        return hidden, _softmax(logits)

    def predict_proba(self, weights: Weights, X: np.ndarray) -> np.ndarray:
        features = self._prepare(X).astype(np.float64)
        w64 = {k: np.asarray(v, dtype=np.float64) for k, v in weights.items()}
        outputs = []
        for start in range(0, len(features), 8192):
            outputs.append(self._forward(w64, features[start : start + 8192])[1])
        if not outputs:
            return np.zeros((0, self.task.num_classes))
        return np.concatenate(outputs, axis=0)

    # ------------------------------------------------------------ training
    def train_local(self, weights: Weights, dataset: ArrayDataset, config: TrainConfig) -> TrainResult:
        config.validate()
        if config.class_weighting != "none" or config.proximal_mu > 0:
            raise ValueError("Class weighting and FedProx are implemented for the PyTorch models only")
        started = time.perf_counter()
        features = self._prepare(dataset.X).astype(np.float64)
        labels = np.asarray(dataset.y, dtype=np.int64)
        n = len(labels)
        if n < 2:
            raise ValueError("Local training needs at least 2 samples")

        params = {k: np.asarray(v, dtype=np.float64).copy() for k, v in weights.items()}
        m = {k: np.zeros_like(v) for k, v in params.items()}
        v = {k: np.zeros_like(p) for k, p in params.items()}
        beta1, beta2, eps = 0.9, 0.999, 1e-8
        rng = np.random.default_rng(config.seed)
        step = 0
        history = []

        for epoch in range(config.local_epochs):
            order = rng.permutation(n)
            loss_sum, correct = 0.0, 0
            for start in range(0, n, config.batch_size):
                batch = order[start : start + config.batch_size]
                xb, yb = features[batch], labels[batch]
                hidden, probs = self._forward(params, xb)
                loss_sum += float(-np.sum(np.log(np.clip(probs[np.arange(len(yb)), yb], 1e-12, 1.0))))
                correct += int(np.sum(np.argmax(probs, axis=1) == yb))

                grad_logits = probs.copy()
                grad_logits[np.arange(len(yb)), yb] -= 1.0
                grad_logits /= len(yb)
                grads = {
                    "W2": hidden.T @ grad_logits,
                    "b2": grad_logits.sum(axis=0),
                }
                grad_hidden = (grad_logits @ params["W2"].T) * (hidden > 0)
                grads["W1"] = xb.T @ grad_hidden
                grads["b1"] = grad_hidden.sum(axis=0)

                step += 1
                for key in params:
                    m[key] = beta1 * m[key] + (1 - beta1) * grads[key]
                    v[key] = beta2 * v[key] + (1 - beta2) * grads[key] ** 2
                    m_hat = m[key] / (1 - beta1**step)
                    v_hat = v[key] / (1 - beta2**step)
                    params[key] -= config.learning_rate * m_hat / (np.sqrt(v_hat) + eps)
            history.append({"epoch": epoch + 1, "loss": loss_sum / n, "accuracy": correct / n})

        return TrainResult(
            weights={k: p.astype(np.float32) for k, p in params.items()},
            num_samples=n,
            history=history,
            duration_seconds=time.perf_counter() - started,
        )


def _prepare_xray_flat(X: np.ndarray) -> np.ndarray:
    images = prepare_xray(X)
    small = block_downsample(images, _XRAY_REFERENCE_SIZE)
    return small.reshape(len(small), -1) - 0.5


def build_reference_adapter(modality: str) -> NumpyMLPAdapter:
    if modality == "ehr":
        return NumpyMLPAdapter("ehr", NUM_EHR_FEATURES, 32, standardize_ehr)
    if modality == "ecg":
        return NumpyMLPAdapter("ecg", ECG_BEAT_LENGTH, 64, prepare_ecg)
    if modality == "xray":
        return NumpyMLPAdapter("xray", _XRAY_REFERENCE_SIZE * _XRAY_REFERENCE_SIZE, 64, _prepare_xray_flat)
    raise ValueError(f"Unknown modality '{modality}'")
