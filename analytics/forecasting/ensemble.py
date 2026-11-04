"""Ensemble weights and empirical intervals, both fitted on validation forecasts only."""

from __future__ import annotations

from typing import Tuple

import numpy as np


def simplex_weights(predictions: np.ndarray, actual: np.ndarray, sample_weight: np.ndarray | None = None) -> np.ndarray:
    """Non-negative weights summing to 1 that minimise the (weighted) squared error of the combination.

    ``predictions`` is [n_forecasts, n_members]. Solved by projected gradient descent on the simplex, which
    converges for this convex problem; deterministic, no tuning.
    """
    predictions = np.asarray(predictions, dtype=np.float64)
    actual = np.asarray(actual, dtype=np.float64)
    if predictions.ndim != 2 or len(predictions) != len(actual) or len(actual) == 0:
        raise ValueError("predictions must be [n, members] with one actual value per row")
    w_rows = np.ones(len(actual)) if sample_weight is None else np.asarray(sample_weight, dtype=np.float64)
    gram = predictions.T @ (predictions * w_rows[:, None])
    linear = predictions.T @ (actual * w_rows)
    step = 1.0 / max(np.linalg.eigvalsh(gram).max(), 1e-12)
    weights = np.full(predictions.shape[1], 1.0 / predictions.shape[1])
    for _ in range(20000):
        updated = project_to_simplex(weights - step * (gram @ weights - linear))
        if np.max(np.abs(updated - weights)) < 1e-12:
            weights = updated
            break
        weights = updated
    return weights


def project_to_simplex(v: np.ndarray) -> np.ndarray:
    """Euclidean projection onto {w : w >= 0, sum(w) = 1}."""
    v = np.asarray(v, dtype=np.float64)
    u = np.sort(v)[::-1]
    cumulative = np.cumsum(u) - 1.0
    rho = np.nonzero(u - cumulative / np.arange(1, len(u) + 1) > 0)[0][-1]
    theta = cumulative[rho] / (rho + 1.0)
    return np.maximum(v - theta, 0.0)


def residual_quantiles(scaled_residuals: np.ndarray, level: float = 0.8) -> Tuple[float, float]:
    """Lower and upper quantiles of (actual - forecast) / scale for a central interval of ``level``."""
    tail = (1.0 - level) / 2.0
    residuals = np.asarray(scaled_residuals, dtype=np.float64)
    return float(np.quantile(residuals, tail)), float(np.quantile(residuals, 1.0 - tail))
