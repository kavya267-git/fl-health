"""Shapley-value feature attribution for tabular models (SHAP).

Implements the permutation-sampling estimator of interventional Shapley
values against a background sample - the same quantity the ``shap`` library's
Kernel and Permutation explainers estimate. For one record ``x`` and model
output ``f``:

* ``base_value`` is the mean of ``f`` over the background rows;
* each feature's value is the average change in ``f`` when that feature is
  switched from the background rows' values to ``x``'s value, over random
  feature orderings;
* the values add up exactly: ``base_value + sum(values) == f(x)``.

The estimator is model-agnostic: it only needs a ``predict`` function, so it
works for TabNet and for the NumPy reference model alike.
"""

from __future__ import annotations

from typing import Callable, Optional

import numpy as np

PredictFn = Callable[[np.ndarray], np.ndarray]

METHOD_NAME = "Shapley values (permutation sampling, interventional, background sample)"


def shapley_values(
    predict: PredictFn,
    x: np.ndarray,
    background: np.ndarray,
    n_permutations: int = 32,
    rng: Optional[np.random.Generator] = None,
) -> dict:
    """Shapley values for one record.

    ``predict`` maps [n, d] inputs to [n, n_outputs]. Returns ``values`` with
    shape [d, n_outputs], ``base_value`` [n_outputs] and ``prediction`` [n_outputs].
    Each sampled ordering is also evaluated in reverse (antithetic sampling),
    which lowers variance at no extra design cost.
    """
    rng = rng or np.random.default_rng(0)
    x = np.asarray(x, dtype=np.float32).reshape(-1)
    background = np.asarray(background, dtype=np.float32)
    if background.ndim != 2 or background.shape[1] != x.shape[0]:
        raise ValueError("background must have shape [n_background, n_features] matching x")
    if len(background) == 0:
        raise ValueError("background sample is empty")
    if n_permutations < 1:
        raise ValueError("n_permutations must be at least 1")

    n_features = x.shape[0]
    n_background = len(background)
    orderings = []
    for _ in range(n_permutations):
        order = rng.permutation(n_features)
        orderings.append(order)
        orderings.append(order[::-1])

    # For each ordering build d+1 copies of the background, switching one more
    # feature to x's value at each step, then score everything in one call.
    stacked = np.empty((len(orderings), n_features + 1, n_background, n_features), dtype=np.float32)
    for index, order in enumerate(orderings):
        current = background.copy()
        stacked[index, 0] = current
        for step, feature in enumerate(order, start=1):
            current[:, feature] = x[feature]
            stacked[index, step] = current
    outputs = np.asarray(predict(stacked.reshape(-1, n_features)), dtype=np.float64)
    n_outputs = outputs.shape[1]
    means = outputs.reshape(len(orderings), n_features + 1, n_background, n_outputs).mean(axis=2)

    values = np.zeros((n_features, n_outputs), dtype=np.float64)
    for index, order in enumerate(orderings):
        steps = np.diff(means[index], axis=0)  # [d, n_outputs], in ordering sequence
        values[order] += steps
    values /= len(orderings)

    return {
        "values": values,
        "base_value": means[0, 0],
        "prediction": means[0, -1],
        "n_permutations": len(orderings),
        "n_background": n_background,
    }


def global_importance(
    predict: PredictFn,
    X: np.ndarray,
    background: np.ndarray,
    output_index: int,
    n_permutations: int = 16,
    rng: Optional[np.random.Generator] = None,
) -> dict:
    """Aggregate attribution over a sample of records.

    Returns only aggregates - mean absolute Shapley value per feature and the
    direction in which each feature pushes the output - so a hospital can share
    the result without sharing any record.
    """
    rng = rng or np.random.default_rng(0)
    X = np.asarray(X, dtype=np.float32)
    if len(X) == 0:
        raise ValueError("No records to explain")
    per_record = np.stack(
        [shapley_values(predict, row, background, n_permutations, rng)["values"][:, output_index] for row in X]
    )
    mean_abs = np.abs(per_record).mean(axis=0)
    direction = np.zeros(X.shape[1])
    for feature in range(X.shape[1]):
        spread_x, spread_phi = X[:, feature].std(), per_record[:, feature].std()
        if spread_x > 1e-9 and spread_phi > 1e-12:
            direction[feature] = float(np.corrcoef(X[:, feature], per_record[:, feature])[0, 1])
    return {
        "mean_abs": mean_abs,
        "direction": direction,
        "num_records": int(len(X)),
        "n_background": int(len(background)),
        "n_permutations": int(2 * n_permutations),
    }


def shap_library_values(predict: PredictFn, x: np.ndarray, background: np.ndarray, output_index: int) -> dict:
    """Optional alternative that delegates to the ``shap`` package (not required).

    Enabled with ``EXPLAINER_BACKEND=shap-library``. Raises ImportError if the
    package is not installed so the caller can report an explicit error.
    """
    import shap  # noqa: WPS433 - optional dependency

    explainer = shap.KernelExplainer(lambda data: np.asarray(predict(data))[:, output_index], background)
    values = np.asarray(explainer.shap_values(np.asarray(x).reshape(1, -1), silent=True)).reshape(-1)
    return {
        "values": values,
        "base_value": float(np.ravel(explainer.expected_value)[0]),
        "n_background": int(len(background)),
    }
