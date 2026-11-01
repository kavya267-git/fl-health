"""Federated Averaging and model-compatibility rules."""

import numpy as np
import pytest

from app.federated.fedavg import ClientUpdate, aggregation_weights, federated_average
from ml.common.weights import IncompatibleWeightsError
from ml.registry import get_adapter


def _weights(value: float):
    return {"layer.weight": np.full((2, 3), value, dtype=np.float32), "layer.bias": np.full(3, value, dtype=np.float32)}


def test_weighted_by_sample_count():
    updates = [ClientUpdate("a", _weights(1.0), 100), ClientUpdate("b", _weights(4.0), 300)]
    averaged = federated_average(updates)
    # (100 * 1 + 300 * 4) / 400 = 3.25
    assert np.allclose(averaged["layer.weight"], 3.25)
    assert np.allclose(averaged["layer.bias"], 3.25)
    assert averaged["layer.weight"].dtype == np.float32
    assert aggregation_weights(updates) == {"a": 0.25, "b": 0.75}


def test_equal_weights_reduce_to_plain_mean():
    updates = [ClientUpdate(str(i), _weights(float(i)), 50) for i in range(4)]
    assert np.allclose(federated_average(updates)["layer.bias"], 1.5)


def test_single_client_returns_its_weights():
    averaged = federated_average([ClientUpdate("a", _weights(2.5), 10)])
    assert np.allclose(averaged["layer.weight"], 2.5)


def test_integer_buffers_are_averaged_and_keep_dtype():
    first = {**_weights(1.0), "bn.num_batches_tracked": np.array(10, dtype=np.int64)}
    second = {**_weights(1.0), "bn.num_batches_tracked": np.array(21, dtype=np.int64)}
    averaged = federated_average([ClientUpdate("a", first, 1), ClientUpdate("b", second, 1)])
    assert averaged["bn.num_batches_tracked"].dtype == np.int64
    assert int(averaged["bn.num_batches_tracked"]) in (15, 16)


def test_rejects_different_shapes():
    other = {"layer.weight": np.zeros((2, 4), dtype=np.float32), "layer.bias": np.zeros(3, dtype=np.float32)}
    with pytest.raises(IncompatibleWeightsError):
        federated_average([ClientUpdate("a", _weights(1.0), 10), ClientUpdate("b", other, 10)])


def test_rejects_different_tensor_names():
    other = {"other.weight": np.zeros((2, 3), dtype=np.float32), "layer.bias": np.zeros(3, dtype=np.float32)}
    with pytest.raises(IncompatibleWeightsError):
        federated_average([ClientUpdate("a", _weights(1.0), 10), ClientUpdate("b", other, 10)])


def test_never_averages_models_of_different_modalities():
    ehr = get_adapter("ehr").init_weights(0)
    ecg = get_adapter("ecg").init_weights(0)
    with pytest.raises(IncompatibleWeightsError):
        federated_average([ClientUpdate("a", ehr, 10), ClientUpdate("b", ecg, 10)])


def test_rejects_non_finite_and_empty_inputs():
    bad = _weights(1.0)
    bad["layer.bias"][0] = np.nan
    with pytest.raises(IncompatibleWeightsError):
        federated_average([ClientUpdate("a", bad, 10)])
    with pytest.raises(ValueError):
        federated_average([])
    with pytest.raises(ValueError):
        federated_average([ClientUpdate("a", _weights(1.0), 0)])


def test_modalities_have_distinct_architecture_signatures():
    signatures = {modality: get_adapter(modality).signature() for modality in ("ehr", "ecg", "xray")}
    assert len(set(signatures.values())) == 3
