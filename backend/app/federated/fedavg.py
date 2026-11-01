"""Federated Averaging (McMahan et al., 2017).

    W_global = sum_k (n_k / N) * W_k

where ``W_k`` are hospital k's weights after local training, ``n_k`` is the
number of local training samples it used and ``N`` is the total over the
participating hospitals.

The function refuses to average updates whose tensors do not line up exactly,
so models of different architectures (or different modalities) can never be
mixed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

import numpy as np

from ml.common.weights import IncompatibleWeightsError, all_finite, assert_same_structure

Weights = Dict[str, np.ndarray]


@dataclass
class ClientUpdate:
    hospital_id: str
    weights: Weights
    num_samples: int


def aggregation_weights(updates: List[ClientUpdate]) -> Dict[str, float]:
    """The n_k / N coefficient applied to each hospital."""
    total = sum(update.num_samples for update in updates)
    if total <= 0:
        raise ValueError("Total number of samples must be positive")
    return {update.hospital_id: update.num_samples / total for update in updates}


def federated_average(updates: List[ClientUpdate]) -> Weights:
    if not updates:
        raise ValueError("No updates to aggregate")
    for update in updates:
        if update.num_samples <= 0:
            raise ValueError(f"Update from {update.hospital_id} reports {update.num_samples} samples")
        if not all_finite(update.weights):
            raise IncompatibleWeightsError(f"Update from {update.hospital_id} contains NaN or infinite values")

    reference = updates[0].weights
    for update in updates[1:]:
        try:
            assert_same_structure(reference, update.weights)
        except IncompatibleWeightsError as exc:
            raise IncompatibleWeightsError(
                f"Update from {update.hospital_id} is not compatible with {updates[0].hospital_id}: {exc}"
            ) from exc

    coefficients = aggregation_weights(updates)
    averaged: Weights = {}
    for key, reference_tensor in reference.items():
        reference_tensor = np.asarray(reference_tensor)
        accumulator = np.zeros(reference_tensor.shape, dtype=np.float64)
        for update in updates:
            accumulator += coefficients[update.hospital_id] * np.asarray(update.weights[key], dtype=np.float64)
        if np.issubdtype(reference_tensor.dtype, np.floating):
            averaged[key] = accumulator.astype(reference_tensor.dtype)
        else:
            # Integer buffers (e.g. batch-norm step counters) are averaged and rounded.
            averaged[key] = np.rint(accumulator).astype(reference_tensor.dtype)
    return averaged
