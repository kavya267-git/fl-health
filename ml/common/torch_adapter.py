"""Base class for the PyTorch model adapters.

Imported only when PyTorch is installed (see ``ml.registry``).
"""

from __future__ import annotations

import os
import time
from abc import abstractmethod
from typing import Optional

import numpy as np
import torch
from torch import nn

from ml.common.adapter import ModelAdapter
from ml.common.types import ArrayDataset, TrainConfig, TrainResult, Weights

_PREDICT_BATCH = 256
_GRAD_CLIP_NORM = 5.0


def resolve_device() -> torch.device:
    requested = os.getenv("FL_DEVICE", "auto").lower()
    if requested == "cpu":
        return torch.device("cpu")
    if requested in ("cuda", "auto") and torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def state_dict_to_weights(state_dict) -> Weights:
    return {key: value.detach().cpu().numpy().copy() for key, value in state_dict.items()}


def weights_to_state_dict(weights: Weights, reference_state) -> dict:
    """Convert NumPy weights into tensors matching the model's own dtypes and shapes."""
    state = {}
    for key, reference in reference_state.items():
        if key not in weights:
            raise KeyError(f"Weights are missing tensor '{key}'")
        tensor = torch.tensor(np.asarray(weights[key]))
        state[key] = tensor.to(dtype=reference.dtype).reshape(reference.shape)
    return state


class TorchModelAdapter(ModelAdapter):
    backend = "pytorch"

    # --------------------------------------------------------------- hooks
    @abstractmethod
    def build_model(self, for_init: bool = False) -> nn.Module:
        """Construct the network. ``for_init`` is True only when creating version 0."""

    @abstractmethod
    def to_input(self, X: np.ndarray) -> torch.Tensor:
        """Convert a batch of raw inputs into the float tensor the network expects."""

    def regulariser(self, model: nn.Module) -> Optional[torch.Tensor]:
        """Optional extra loss term evaluated after a forward pass."""
        return None

    # ------------------------------------------------------------- weights
    def init_weights(self, seed: int = 0) -> Weights:
        torch.manual_seed(seed)
        model = self.build_model(for_init=True)
        return state_dict_to_weights(model.state_dict())

    def reference_weights(self) -> Weights:
        # Never triggers a pretrained-weights download; only names and shapes matter.
        return state_dict_to_weights(self.build_model(for_init=False).state_dict())

    def load_model(self, weights: Weights) -> nn.Module:
        model = self.build_model(for_init=False)
        model.load_state_dict(weights_to_state_dict(weights, model.state_dict()), strict=True)
        return model

    # ------------------------------------------------------------ training
    def train_local(self, weights: Weights, dataset: ArrayDataset, config: TrainConfig) -> TrainResult:
        config.validate()
        started = time.perf_counter()
        n = len(dataset)
        if n < 2:
            raise ValueError("Local training needs at least 2 samples")

        torch.manual_seed(config.seed)
        device = resolve_device()
        model = self.load_model(weights).to(device)
        model.train()
        optimizer = torch.optim.Adam(model.parameters(), lr=config.learning_rate)
        labels = np.asarray(dataset.y, dtype=np.int64)
        criterion = nn.CrossEntropyLoss(weight=self._class_weights(labels, config.class_weighting, device))
        # FedProx: keep the starting (global) parameters to pull the local model towards them.
        anchor = [p.detach().clone() for p in model.parameters()] if config.proximal_mu > 0 else None
        generator = torch.Generator().manual_seed(config.seed)
        history = []

        for epoch in range(config.local_epochs):
            order = torch.randperm(n, generator=generator).numpy()
            loss_sum, correct, seen = 0.0, 0, 0
            for start in range(0, n, config.batch_size):
                batch = order[start : start + config.batch_size]
                if len(batch) < 2:  # batch normalisation cannot train on one sample
                    continue
                inputs = self.to_input(dataset.X[batch]).to(device)
                targets = torch.from_numpy(labels[batch]).to(device)
                optimizer.zero_grad()
                logits = model(inputs)
                loss = criterion(logits, targets)
                total = loss
                extra = self.regulariser(model)
                if extra is not None:
                    total = total + extra
                if anchor is not None:
                    proximal = sum(torch.sum((p - a) ** 2) for p, a in zip(model.parameters(), anchor))
                    total = total + 0.5 * config.proximal_mu * proximal
                total.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), _GRAD_CLIP_NORM)
                optimizer.step()
                loss_sum += float(loss.item()) * len(batch)
                correct += int((logits.argmax(dim=1) == targets).sum().item())
                seen += len(batch)
            history.append(
                {
                    "epoch": epoch + 1,
                    "loss": loss_sum / max(seen, 1),
                    "accuracy": correct / max(seen, 1),
                }
            )

        model.eval()
        return TrainResult(
            weights=state_dict_to_weights(model.state_dict()),
            num_samples=n,
            history=history,
            duration_seconds=time.perf_counter() - started,
        )

    def _class_weights(self, labels: np.ndarray, scheme: str, device) -> Optional[torch.Tensor]:
        """Per-class loss weights from this hospital's own label counts (None = unweighted)."""
        if scheme == "none":
            return None
        k = self.task.num_classes
        counts = np.bincount(labels, minlength=k).astype(np.float64)
        # A class this hospital never sees gets weight 0; it contributes no loss terms anyway.
        weights = np.where(counts > 0, len(labels) / (k * np.maximum(counts, 1.0)), 0.0)
        return torch.tensor(weights, dtype=torch.float32, device=device)

    # ----------------------------------------------------------- inference
    def predict_proba(self, weights: Weights, X: np.ndarray) -> np.ndarray:
        device = resolve_device()
        model = self.load_model(weights).to(device)
        model.eval()
        outputs = []
        with torch.no_grad():
            for start in range(0, len(X), _PREDICT_BATCH):
                inputs = self.to_input(X[start : start + _PREDICT_BATCH]).to(device)
                outputs.append(torch.softmax(model(inputs), dim=1).cpu().numpy())
        if not outputs:
            return np.zeros((0, self.task.num_classes), dtype=np.float64)
        return np.concatenate(outputs, axis=0).astype(np.float64)
