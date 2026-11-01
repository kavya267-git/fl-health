"""Selects the model implementation for each modality.

``ML_BACKEND`` controls the choice:

* ``auto`` (default) - PyTorch models when PyTorch is importable, otherwise the
  NumPy reference models.
* ``pytorch`` - TabNet / CNN-BiLSTM / EfficientNet-B3. Fails loudly if PyTorch
  (or torchvision for X-ray) is missing.
* ``numpy-reference`` - the lightweight stand-in models in ``ml.reference``.
"""

from __future__ import annotations

import importlib.util
import os
from functools import lru_cache
from typing import Dict

from ml.common.adapter import ModelAdapter
from ml.common.types import MODALITIES
from ml.reference import build_reference_adapter

VALID_BACKENDS = ("auto", "pytorch", "numpy-reference")


class BackendUnavailableError(RuntimeError):
    pass


def torch_available() -> bool:
    return importlib.util.find_spec("torch") is not None


def torchvision_available() -> bool:
    return importlib.util.find_spec("torchvision") is not None


def configured_backend() -> str:
    value = os.getenv("ML_BACKEND", "auto").strip().lower()
    if value not in VALID_BACKENDS:
        raise ValueError(f"ML_BACKEND must be one of {VALID_BACKENDS}, got '{value}'")
    return value


def resolve_backend(modality: str, requested: str | None = None) -> str:
    requested = requested or configured_backend()
    needs_vision = modality == "xray"
    have_torch = torch_available() and (torchvision_available() or not needs_vision)
    if requested == "numpy-reference":
        return "numpy-reference"
    if requested == "pytorch":
        if not have_torch:
            missing = "torch and torchvision" if needs_vision else "torch"
            raise BackendUnavailableError(
                f"ML_BACKEND=pytorch but {missing} is not installed. "
                "Install it (see backend/requirements.txt) or set ML_BACKEND=auto."
            )
        return "pytorch"
    return "pytorch" if have_torch else "numpy-reference"


def _build_torch_adapter(modality: str) -> ModelAdapter:
    if modality == "ehr":
        from ml.ehr.tabnet import TabNetAdapter

        return TabNetAdapter()
    if modality == "ecg":
        from ml.ecg.cnn_bilstm import CNNBiLSTMAdapter

        return CNNBiLSTMAdapter()
    if modality == "xray":
        from ml.xray.efficientnet import EfficientNetB3Adapter

        return EfficientNetB3Adapter()
    raise ValueError(f"Unknown modality '{modality}'")


@lru_cache(maxsize=None)
def _cached_adapter(modality: str, backend: str) -> ModelAdapter:
    if backend == "pytorch":
        return _build_torch_adapter(modality)
    return build_reference_adapter(modality)


def get_adapter(modality: str, backend: str | None = None) -> ModelAdapter:
    if modality not in MODALITIES:
        raise ValueError(f"Unknown modality '{modality}'. Expected one of {MODALITIES}")
    return _cached_adapter(modality, resolve_backend(modality, backend))


#: Target architecture per modality, independent of which backend is active.
TARGET_ARCHITECTURES: Dict[str, str] = {"ehr": "TabNet", "ecg": "CNN-BiLSTM", "xray": "EfficientNet-B3"}
