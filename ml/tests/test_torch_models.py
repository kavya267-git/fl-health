"""PyTorch models: TabNet, CNN-BiLSTM and EfficientNet-B3.

Skipped automatically when PyTorch (or torchvision, for X-ray) is not installed.
"""

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from ml.common.types import ArrayDataset, TrainConfig  # noqa: E402
from ml.common.weights import weights_from_bytes, weights_to_bytes  # noqa: E402
from ml.registry import get_adapter  # noqa: E402
from ml.simulation.ecg import simulate_ecg  # noqa: E402
from ml.simulation.ehr import simulate_ehr  # noqa: E402
from ml.simulation.xray import simulate_xray  # noqa: E402

SIMULATORS = {"ehr": simulate_ehr, "ecg": simulate_ecg, "xray": simulate_xray}
EXPECTED = {"ehr": "TabNet", "ecg": "CNN-BiLSTM", "xray": "EfficientNet-B3"}


def _adapter(modality):
    if modality == "xray":
        pytest.importorskip("torchvision")
    return get_adapter(modality, "pytorch")


def _dataset(modality, n, seed):
    X, y = SIMULATORS[modality](n, np.random.default_rng(seed))
    return ArrayDataset(X, y, modality, "train", "simulated")


@pytest.mark.parametrize("modality", ["ehr", "ecg", "xray"])
def test_architecture_and_initialisation(modality):
    adapter = _adapter(modality)
    assert adapter.architecture == EXPECTED[modality] and adapter.backend == "pytorch"
    weights = adapter.init_weights(0)
    again = adapter.init_weights(0)
    assert all(np.array_equal(weights[k], again[k]) for k in weights)
    assert adapter.signature(weights) == adapter.signature()
    assert adapter.num_parameters() > 1000


@pytest.mark.parametrize("modality", ["ehr", "ecg", "xray"])
def test_forward_pass_gives_class_probabilities(modality):
    adapter = _adapter(modality)
    data = _dataset(modality, 12, 0)
    probabilities = adapter.predict_proba(adapter.init_weights(0), data.X)
    assert probabilities.shape == (12, adapter.task.num_classes)
    assert np.allclose(probabilities.sum(axis=1), 1.0, atol=1e-5)


@pytest.mark.parametrize("modality,n,epochs", [("ehr", 256, 5), ("ecg", 160, 3), ("xray", 24, 1)])
def test_local_training_changes_weights_and_reports_history(modality, n, epochs):
    adapter = _adapter(modality)
    data = _dataset(modality, n, 1)
    initial = adapter.init_weights(0)
    result = adapter.train_local(initial, data, TrainConfig(local_epochs=epochs, batch_size=16, learning_rate=0.003))
    assert result.num_samples == n and len(result.history) == epochs
    assert set(result.weights) == set(initial)
    changed = [k for k in initial if not np.array_equal(initial[k], result.weights[k])]
    assert changed, "training did not change any tensor"
    assert all(np.isfinite(v).all() for v in result.weights.values() if np.issubdtype(v.dtype, np.floating))
    if modality != "xray":
        assert result.history[-1]["loss"] < result.history[0]["loss"]


@pytest.mark.parametrize("modality", ["ehr", "ecg", "xray"])
def test_weights_survive_save_and_load(modality):
    adapter = _adapter(modality)
    data = _dataset(modality, 8, 2)
    weights = adapter.init_weights(3)
    restored = weights_from_bytes(weights_to_bytes(weights))
    assert adapter.signature(restored) == adapter.signature(weights)
    assert np.allclose(adapter.predict_proba(restored, data.X), adapter.predict_proba(weights, data.X), atol=1e-6)


def test_tabnet_shared_layers_are_serialised_once():
    """Shared feature-transformer layers must appear under one name only."""
    adapter = _adapter("ehr")
    model = adapter.build_model()
    seen = {}
    for name, parameter in model.named_parameters():
        assert id(parameter) not in seen, f"{name} duplicates {seen.get(id(parameter))}"
        seen[id(parameter)] = name
    state = model.state_dict()
    pointers = [tensor.data_ptr() for tensor in state.values() if tensor.numel() > 1]
    assert len(pointers) == len(set(pointers))


def test_tabnet_sparsemax_and_masks():
    from ml.ehr.tabnet import Sparsemax

    output = Sparsemax()(torch.tensor([[2.0, 1.0, -1.0], [0.5, 0.5, 0.5]]))
    assert torch.allclose(output.sum(dim=1), torch.ones(2), atol=1e-6)
    assert (output >= 0).all() and output[0, 2] == 0
    adapter = _adapter("ehr")
    model = adapter.load_model(adapter.init_weights(0))
    model.eval()
    model(adapter.to_input(_dataset("ehr", 5, 0).X))
    assert len(model.last_masks) == model.n_steps
    assert torch.allclose(model.last_masks[0].sum(dim=1), torch.ones(5), atol=1e-5)
    assert model.last_sparsity_loss is not None


def test_fedavg_of_torch_weights_loads_back_into_the_model():
    from ml.common.weights import assert_same_structure

    adapter = _adapter("ecg")
    first, second = adapter.init_weights(0), adapter.init_weights(1)
    assert_same_structure(first, second)
    averaged = {}
    for key in first:
        mean = (first[key].astype(np.float64) + second[key].astype(np.float64)) / 2
        averaged[key] = (
            mean.astype(first[key].dtype)
            if np.issubdtype(first[key].dtype, np.floating)
            else np.rint(mean).astype(first[key].dtype)
        )
    probabilities = adapter.predict_proba(averaged, _dataset("ecg", 4, 0).X)
    assert probabilities.shape == (4, 4)


def test_grad_cam_produces_a_normalised_heatmap():
    pytest.importorskip("torchvision")
    from analytics.explainability.gradcam import grad_cam, supports_gradcam

    adapter = _adapter("xray")
    assert supports_gradcam(adapter)
    image = _dataset("xray", 1, 0).X[0]
    result = grad_cam(adapter, adapter.init_weights(0), image)
    assert result["heatmap"].shape == image.shape
    assert 0.0 <= result["heatmap"].min() and result["heatmap"].max() <= 1.0 + 1e-6
    assert result["probabilities"].shape == (2,)


# ------------------------------------------------- experiment options (opt-in)
def test_training_options_default_to_the_platform_behaviour():
    config = TrainConfig()
    assert config.class_weighting == "none" and config.proximal_mu == 0.0


def test_balanced_class_weights_come_from_local_label_counts():
    adapter = _adapter("ehr")
    labels = np.array([0] * 8 + [1] * 2)
    weights = adapter._class_weights(labels, "balanced", torch.device("cpu"))
    assert torch.allclose(weights, torch.tensor([10 / (2 * 8), 10 / (2 * 2)]))
    assert adapter._class_weights(labels, "none", torch.device("cpu")) is None
    missing = adapter._class_weights(np.array([0, 0, 0]), "balanced", torch.device("cpu"))
    assert missing[1] == 0  # a class this hospital never sees gets no weight


def test_class_weighting_changes_training():
    adapter = _adapter("ehr")
    data = _dataset("ehr", 128, 4)
    start = adapter.init_weights(0)
    plain = adapter.train_local(start, data, TrainConfig(local_epochs=2, batch_size=16, seed=1)).weights
    weighted = adapter.train_local(
        start, data, TrainConfig(local_epochs=2, batch_size=16, seed=1, class_weighting="balanced")
    ).weights
    assert any(not np.allclose(plain[k], weighted[k]) for k in plain)


def test_proximal_term_keeps_the_local_model_closer_to_the_global_one():
    from analytics.privacy.dp import update_norm

    adapter = _adapter("ecg")
    data = _dataset("ecg", 96, 5)
    start = adapter.init_weights(0)
    drift = {
        mu: update_norm(
            start,
            adapter.train_local(
                start, data, TrainConfig(local_epochs=2, batch_size=16, seed=1, proximal_mu=mu)
            ).weights,
        )
        for mu in (0.0, 10.0)
    }
    assert drift[10.0] < drift[0.0]


def test_numpy_reference_refuses_options_it_does_not_implement():
    reference = get_adapter("ehr", "numpy-reference")
    data = _dataset("ehr", 16, 0)
    with pytest.raises(ValueError, match="PyTorch models only"):
        reference.train_local(reference.init_weights(0), data, TrainConfig(class_weighting="balanced"))
    with pytest.raises(ValueError, match="class_weighting"):
        TrainConfig(class_weighting="sometimes").validate()
