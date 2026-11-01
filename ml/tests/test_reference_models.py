"""NumPy reference models: initialisation, local training, evaluation, save/load."""

import numpy as np
import pytest

from ml.common.types import ArrayDataset, TrainConfig
from ml.common.weights import weights_from_bytes, weights_to_bytes
from ml.evaluation.metrics import metrics_from_evaluation
from ml.reference import build_reference_adapter
from ml.registry import BackendUnavailableError, get_adapter, resolve_backend, torch_available
from ml.simulation.ecg import simulate_ecg
from ml.simulation.ehr import simulate_ehr
from ml.simulation.xray import simulate_xray

SIMULATORS = {"ehr": simulate_ehr, "ecg": simulate_ecg, "xray": simulate_xray}


def _dataset(modality, n, seed, split="train"):
    X, y = SIMULATORS[modality](n, np.random.default_rng(seed))
    return ArrayDataset(X, y, modality, split, "simulated")


@pytest.mark.parametrize("modality", ["ehr", "ecg", "xray"])
def test_initialisation_is_seeded_and_labelled(modality):
    adapter = build_reference_adapter(modality)
    assert adapter.backend == "numpy-reference" and "reference" in adapter.architecture.lower()
    first, second, other = adapter.init_weights(1), adapter.init_weights(1), adapter.init_weights(2)
    assert all(np.array_equal(first[k], second[k]) for k in first)
    assert not np.array_equal(first["W1"], other["W1"])
    assert adapter.signature() == adapter.signature(other)
    assert adapter.describe()["num_parameters"] == sum(v.size for v in first.values())


@pytest.mark.parametrize("modality", ["ehr", "ecg"])
def test_local_training_reduces_loss_and_beats_the_untrained_model(modality):
    adapter = build_reference_adapter(modality)
    train, val = _dataset(modality, 400, 0), _dataset(modality, 200, 1, "val")
    initial = adapter.init_weights(0)
    result = adapter.train_local(initial, train, TrainConfig(local_epochs=6, learning_rate=0.005))
    assert result.num_samples == 400 and len(result.history) == 6
    assert result.history[-1]["loss"] < result.history[0]["loss"]
    before = metrics_from_evaluation(adapter.evaluate(initial, val), adapter.task)
    after = metrics_from_evaluation(adapter.evaluate(result.weights, val), adapter.task)
    assert after["loss"] < before["loss"]
    # The global weights passed in are not modified in place.
    assert all(np.array_equal(initial[k], adapter.init_weights(0)[k]) for k in initial)


def test_training_is_deterministic_for_a_seed():
    adapter = build_reference_adapter("ehr")
    train = _dataset("ehr", 120, 0)
    config = TrainConfig(local_epochs=2, seed=5)
    first = adapter.train_local(adapter.init_weights(0), train, config).weights
    second = adapter.train_local(adapter.init_weights(0), train, config).weights
    assert all(np.array_equal(first[k], second[k]) for k in first)


@pytest.mark.parametrize("modality", ["ehr", "ecg", "xray"])
def test_predictions_are_probabilities_and_survive_save_load(modality):
    adapter = build_reference_adapter(modality)
    data = _dataset(modality, 40, 2)
    weights = adapter.train_local(adapter.init_weights(0), data, TrainConfig(local_epochs=1)).weights
    probabilities = adapter.predict_proba(weights, data.X)
    assert probabilities.shape == (40, adapter.task.num_classes)
    assert np.allclose(probabilities.sum(axis=1), 1.0) and (probabilities >= 0).all()
    restored = weights_from_bytes(weights_to_bytes(weights))
    assert np.allclose(adapter.predict_proba(restored, data.X), probabilities)


def test_training_config_is_validated():
    adapter = build_reference_adapter("ehr")
    data = _dataset("ehr", 20, 0)
    with pytest.raises(ValueError):
        adapter.train_local(adapter.init_weights(0), data, TrainConfig(local_epochs=0))
    with pytest.raises(ValueError):
        adapter.train_local(adapter.init_weights(0), data, TrainConfig(learning_rate=0))
    tiny = ArrayDataset(data.X[:1], data.y[:1], "ehr", "train", "simulated")
    with pytest.raises(ValueError):
        adapter.train_local(adapter.init_weights(0), tiny, TrainConfig())


def test_backend_resolution(monkeypatch):
    assert resolve_backend("ehr", "numpy-reference") == "numpy-reference"
    assert get_adapter("ehr", "numpy-reference").backend == "numpy-reference"
    with pytest.raises(ValueError):
        get_adapter("mri")
    monkeypatch.setenv("ML_BACKEND", "tensorflow")
    with pytest.raises(ValueError):
        resolve_backend("ehr")
    if not torch_available():
        assert resolve_backend("ehr", "auto") == "numpy-reference"
        with pytest.raises(BackendUnavailableError):
            resolve_backend("ehr", "pytorch")
