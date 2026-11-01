"""Validation of a model update before it is accepted for aggregation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np

from ml.common.weights import (
    IncompatibleWeightsError,
    all_finite,
    architecture_signature,
    assert_same_structure,
    l2_distance,
    weights_from_bytes,
    weights_sha256,
)

Weights = Dict[str, np.ndarray]


class UpdateRejected(Exception):
    """The update must not be aggregated. ``reason`` is safe to show to operators."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass
class ValidatedUpdate:
    weights: Weights
    sha256: str
    size_bytes: int
    update_norm: float
    signature: str


def validate_update(
    payload: bytes,
    num_samples: int,
    global_weights: Weights,
    expected_signature: str,
    signature_label: str,
    declared_signature: Optional[str],
    max_bytes: int,
) -> ValidatedUpdate:
    """Check size, format, architecture, finiteness and sample count.

    ``signature_label`` is the "<backend>:<architecture>" string of the global
    model; the update's signature is recomputed from its tensors rather than
    trusted from the client.
    """
    if len(payload) == 0:
        raise UpdateRejected("The update is empty.")
    if len(payload) > max_bytes:
        raise UpdateRejected(f"The update is {len(payload)} bytes; the limit is {max_bytes}.")
    if num_samples <= 0:
        raise UpdateRejected("num_samples must be a positive integer.")

    try:
        weights = weights_from_bytes(payload)
    except IncompatibleWeightsError as exc:
        raise UpdateRejected(str(exc)) from exc

    try:
        assert_same_structure(global_weights, weights)
    except IncompatibleWeightsError as exc:
        raise UpdateRejected(
            f"Incompatible architecture for this round's model: {exc}. "
            "Updates are only aggregated with models of the same architecture."
        ) from exc

    signature = architecture_signature(weights, signature_label)
    if signature != expected_signature:
        raise UpdateRejected("The update's architecture signature does not match the global model.")
    if declared_signature and declared_signature != expected_signature:
        raise UpdateRejected(
            "The hospital node declared a different model architecture or backend than this round uses."
        )
    if not all_finite(weights):
        raise UpdateRejected("The update contains NaN or infinite values.")

    return ValidatedUpdate(
        weights=weights,
        sha256=weights_sha256(weights),
        size_bytes=len(payload),
        update_norm=l2_distance(weights, global_weights),
        signature=signature,
    )
