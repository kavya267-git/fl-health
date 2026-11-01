"""Weights serialisation, compatibility signatures and pooled metrics."""

import io
import pickle

import numpy as np
import pytest

from ml.common.tasks import ECG_TASK, EHR_TASK
from ml.common.types import EvalResult
from ml.common.weights import (
    IncompatibleWeightsError,
    architecture_signature,
    assert_same_structure,
    count_parameters,
    weights_from_bytes,
    weights_sha256,
    weights_to_bytes,
)
from ml.evaluation.metrics import confusion_matrix, evaluate_probabilities, metrics_from_evaluation, pool_evaluations


def _weights():
    rng = np.random.default_rng(0)
    return {
        "a.weight": rng.standard_normal((3, 4)).astype(np.float32),
        "a.bias": rng.standard_normal(4).astype(np.float32),
        "bn.num_batches_tracked": np.array(7, dtype=np.int64),
    }


def test_round_trip_preserves_values_dtypes_and_shapes():
    weights = _weights()
    restored = weights_from_bytes(weights_to_bytes(weights))
    assert set(restored) == set(weights)
    for key in weights:
        assert restored[key].dtype == weights[key].dtype and restored[key].shape == weights[key].shape
        assert np.array_equal(restored[key], weights[key])
    assert weights_sha256(restored) == weights_sha256(weights)


def test_serialisation_is_deterministic():
    assert weights_to_bytes(_weights()) == weights_to_bytes(dict(reversed(list(_weights().items()))))


def test_pickled_payloads_are_refused():
    buffer = io.BytesIO()
    np.savez(buffer, evil=np.array([{"a": 1}], dtype=object))
    with pytest.raises(IncompatibleWeightsError):
        weights_from_bytes(buffer.getvalue())
    with pytest.raises(IncompatibleWeightsError):
        weights_from_bytes(pickle.dumps({"a": 1}))


def test_signature_ignores_values_but_not_structure():
    weights = _weights()
    changed_values = {k: v + 1 for k, v in weights.items()}
    assert architecture_signature(weights, "m") == architecture_signature(changed_values, "m")
    assert architecture_signature(weights, "m") != architecture_signature(weights, "other")
    reshaped = {**weights, "a.bias": np.zeros(5, dtype=np.float32)}
    assert architecture_signature(weights, "m") != architecture_signature(reshaped, "m")
    with pytest.raises(IncompatibleWeightsError):
        assert_same_structure(weights, reshaped)
    assert count_parameters(weights) == 16  # integer buffers are not counted


def test_confusion_and_binary_metrics():
    y_true = np.array([0, 0, 0, 1, 1, 1, 1, 0])
    y_pred = np.array([0, 0, 1, 1, 1, 0, 0, 0])
    matrix = confusion_matrix(y_true, y_pred, 2)
    assert matrix.tolist() == [[3, 1], [2, 2]]
    metrics = metrics_from_evaluation(EvalResult(matrix, loss_sum=4.0, num_samples=8), EHR_TASK)
    assert metrics["accuracy"] == pytest.approx(5 / 8)
    assert metrics["precision"] == pytest.approx(2 / 3)
    assert metrics["recall"] == pytest.approx(2 / 4)
    assert metrics["f1"] == pytest.approx(2 * (2 / 3) * 0.5 / (2 / 3 + 0.5))
    assert metrics["loss"] == pytest.approx(0.5)
    assert "positive class" in metrics["averaging"]


def test_multiclass_metrics_are_macro_averaged():
    matrix = np.diag([10, 5, 5, 0])
    matrix[3, 0] = 4  # every fusion beat called normal
    metrics = metrics_from_evaluation(EvalResult(matrix, 0.0, int(matrix.sum())), ECG_TASK)
    assert metrics["recall"] == pytest.approx((1 + 1 + 1 + 0) / 4)
    assert "macro" in metrics["averaging"]
    assert len(metrics["per_class"]) == 4 and metrics["per_class"][3]["support"] == 4


def test_pooling_hospital_evaluations_equals_centralised_evaluation():
    rng = np.random.default_rng(1)
    probabilities = rng.dirichlet(np.ones(4), size=300)
    labels = rng.integers(0, 4, size=300)
    whole = evaluate_probabilities(probabilities, labels)
    parts = [
        evaluate_probabilities(probabilities[s], labels[s]) for s in (slice(0, 90), slice(90, 200), slice(200, 300))
    ]
    pooled = pool_evaluations(parts)
    assert np.array_equal(pooled.confusion, whole.confusion)
    assert pooled.loss_sum == pytest.approx(whole.loss_sum)
    assert pooled.num_samples == 300
    assert EvalResult.from_dict(pooled.to_dict()).confusion.tolist() == whole.confusion.tolist()


def test_metrics_handle_empty_classes_without_dividing_by_zero():
    metrics = metrics_from_evaluation(EvalResult(np.array([[5, 0], [3, 0]]), 1.0, 8), EHR_TASK)
    assert metrics["precision"] == 0.0 and metrics["recall"] == 0.0 and metrics["f1"] == 0.0
