"""Shapley values and occlusion sensitivity."""

import numpy as np
import pytest

from analytics.explainability.occlusion import occlusion_image, occlusion_signal
from analytics.explainability.service import (
    explain_ecg_beat,
    explain_ehr_record,
    explain_xray_image,
    local_global_importance,
    pool_global_importance,
)
from analytics.explainability.shapley import global_importance, shapley_values
from ml.common.types import ArrayDataset, TrainConfig
from ml.ehr.features import feature_metadata
from ml.reference import build_reference_adapter
from ml.simulation.ecg import simulate_ecg
from ml.simulation.ehr import simulate_ehr
from ml.simulation.xray import simulate_xray


def test_linear_model_matches_the_closed_form():
    """For f(x) = w.x the Shapley value of feature i is w_i * (x_i - mean(background_i))."""
    rng = np.random.default_rng(0)
    w = np.array([2.0, -1.0, 0.5, 0.0])
    background = rng.normal(size=(50, 4)).astype(np.float32)
    x = np.array([1.0, 2.0, -3.0, 4.0], dtype=np.float32)
    result = shapley_values(lambda data: (data @ w)[:, None], x, background, n_permutations=4, rng=rng)
    expected = w * (x - background.mean(axis=0))
    assert np.allclose(result["values"][:, 0], expected, atol=1e-5)
    assert result["values"][3, 0] == pytest.approx(0.0, abs=1e-6)  # unused feature gets nothing


def test_values_add_up_to_the_prediction_for_a_non_linear_model():
    rng = np.random.default_rng(1)
    background = rng.normal(size=(30, 5)).astype(np.float32)
    x = rng.normal(size=5).astype(np.float32)

    def model(data):
        return np.stack([np.tanh(data[:, 0] * data[:, 1]) + data[:, 2] ** 2, data.sum(axis=1)], axis=1)

    result = shapley_values(model, x, background, n_permutations=8, rng=rng)
    assert result["values"].shape == (5, 2)
    assert np.allclose(result["base_value"] + result["values"].sum(axis=0), model(x[None])[0], atol=1e-5)
    assert np.allclose(result["base_value"], model(background).mean(axis=0), atol=1e-5)


def test_symmetric_features_get_equal_credit():
    background = np.zeros((10, 3), dtype=np.float32)
    x = np.array([1.0, 1.0, 5.0], dtype=np.float32)
    result = shapley_values(
        lambda d: (d[:, 0] * d[:, 1])[:, None], x, background, n_permutations=50, rng=np.random.default_rng(2)
    )
    assert result["values"][0, 0] == pytest.approx(result["values"][1, 0], abs=0.08)
    assert result["values"][2, 0] == pytest.approx(0.0, abs=1e-9)


def test_inputs_are_validated():
    with pytest.raises(ValueError):
        shapley_values(lambda d: d[:, :1], np.zeros(3), np.zeros((0, 3)))
    with pytest.raises(ValueError):
        shapley_values(lambda d: d[:, :1], np.zeros(3), np.zeros((5, 4)))


def test_global_importance_ranks_the_feature_that_matters():
    rng = np.random.default_rng(3)
    X = rng.normal(size=(30, 3)).astype(np.float32)
    result = global_importance(lambda d: (3 * d[:, 1])[:, None], X, X[:10], output_index=0, rng=rng)
    assert int(np.argmax(result["mean_abs"])) == 1
    assert result["direction"][1] > 0.99 and result["num_records"] == 30


def test_occlusion_finds_the_part_the_model_uses():
    signal = np.zeros(100, dtype=np.float32)
    signal[40:50] = 1.0

    def model(batch):  # "probability" driven by the bump only
        strength = batch[:, 40:50].mean(axis=1)
        return np.stack([1 - strength, strength], axis=1)

    result = occlusion_signal(model, signal, target_class=1, window=10, stride=5)
    # Only windows that overlap the bump (samples 40-49) can matter.
    assert int(np.argmax(result["importance"])) in range(31, 59)
    assert result["importance"][40:50].min() > 0
    assert result["importance"][:20].max() == pytest.approx(0.0, abs=1e-9)
    assert result["importance"][70:].max() == pytest.approx(0.0, abs=1e-9)

    image = np.zeros((32, 32), dtype=np.float32)
    image[8:16, 20:28] = 1.0

    def image_model(batch):
        strength = batch[:, 8:16, 20:28].mean(axis=(1, 2))
        return np.stack([1 - strength, strength], axis=1)

    heat = occlusion_image(image_model, image, target_class=1, patch=8, stride=4)["importance"]
    row, col = np.unravel_index(np.argmax(heat), heat.shape)
    assert 6 <= row <= 17 and 18 <= col <= 29
    assert heat[24:, :8].max() == pytest.approx(0.0, abs=1e-9)


@pytest.fixture(scope="module")
def trained_ehr():
    adapter = build_reference_adapter("ehr")
    X, y = simulate_ehr(600, np.random.default_rng(0))
    weights = adapter.train_local(
        adapter.init_weights(0),
        ArrayDataset(X, y, "ehr", "train", "simulated"),
        TrainConfig(local_epochs=6, learning_rate=0.005),
    ).weights
    return adapter, weights, X


def test_ehr_record_explanation_payload(trained_ehr):
    adapter, weights, X = trained_ehr
    payload = explain_ehr_record(adapter, weights, X[0], X[1:41], feature_metadata())
    assert payload["scope"] == "individual" and len(payload["contributions"]) == 14
    assert payload["additivity"]["base_plus_contributions"] == pytest.approx(
        payload["additivity"]["model_output"], abs=1e-6
    )
    magnitudes = [abs(c["shap_value"]) for c in payload["contributions"]]
    assert magnitudes == sorted(magnitudes, reverse=True)
    assert {c["direction"] for c in payload["contributions"]} <= {"raises", "lowers", "neutral"}
    assert payload["prediction"]["probability"] == max(p["probability"] for p in payload["prediction"]["probabilities"])


def test_global_importance_is_aggregate_only_and_pools_by_records(trained_ehr):
    adapter, weights, X = trained_ehr
    first = local_global_importance(adapter, weights, X[:40], X[40:100], max_records=10)
    second = local_global_importance(adapter, weights, X[100:140], X[140:200], max_records=5)
    assert first["num_records"] == 10 and len(first["mean_abs"]) == 14
    pooled = pool_global_importance([first, second, None], feature_metadata())
    assert pooled["scope"] == "global" and pooled["metadata"]["hospitals_contributing"] == 2
    assert pooled["metadata"]["records_explained"] == 15
    by_name = {f["feature"]: f["mean_abs_shap"] for f in pooled["features"]}
    expected = (10 * first["mean_abs"][0] + 5 * second["mean_abs"][0]) / 15
    assert by_name["age"] == pytest.approx(expected)
    assert pool_global_importance([None], feature_metadata()) is None
    assert local_global_importance(build_reference_adapter("ecg"), {}, X, X) is None


def test_signal_and_image_explanations():
    ecg = build_reference_adapter("ecg")
    signals, labels = simulate_ecg(200, np.random.default_rng(0))
    weights = ecg.train_local(
        ecg.init_weights(0), ArrayDataset(signals, labels, "ecg", "train", "simulated"), TrainConfig(local_epochs=3)
    ).weights
    payload = explain_ecg_beat(ecg, weights, signals[0], 125)
    assert len(payload["signal"]) == len(payload["importance"]) == 187
    assert "Occlusion" in payload["method"]
    assert 0 <= payload["most_influential_segment"]["start_ms"] < payload["most_influential_segment"]["end_ms"] <= 1500

    xray = build_reference_adapter("xray")
    images, _ = simulate_xray(4, np.random.default_rng(0))
    payload = explain_xray_image(xray, xray.init_weights(0), images[0])
    heatmap = np.array(payload["heatmap"])
    assert heatmap.shape == (64, 64) and heatmap.min() >= 0 and heatmap.max() <= 1
    assert "Occlusion" in payload["method"] and "Grad-CAM needs" in payload["metadata"]["note"]
    assert payload["image_png_base64"].startswith("iVBOR")  # PNG signature in base64
