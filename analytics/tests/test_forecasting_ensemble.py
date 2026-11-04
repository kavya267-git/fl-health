"""Prophet adapter, global LSTM, ensemble weights and the backtest's leakage rules."""

import importlib.util

import numpy as np
import pandas as pd
import pytest

from analytics.forecasting.ensemble import project_to_simplex, residual_quantiles, simplex_weights
from analytics.forecasting.lstm import GlobalLSTM, LSTMSettings, training_windows
from analytics.forecasting.models import ProphetForecaster, candidate_models

HAS_PROPHET = importlib.util.find_spec("prophet") is not None
HAS_TORCH = importlib.util.find_spec("torch") is not None


def test_projection_lands_on_the_simplex():
    for v in ([0.2, 0.3, 0.5], [3.0, -1.0, 0.5], [-2.0, -2.0, -2.0], [10.0, 0.0, 0.0]):
        w = project_to_simplex(np.array(v))
        assert np.all(w >= 0) and w.sum() == pytest.approx(1.0)
    assert project_to_simplex(np.array([0.2, 0.3, 0.5])) == pytest.approx([0.2, 0.3, 0.5])


def test_weights_are_non_negative_sum_to_one_and_recover_a_known_mix():
    rng = np.random.default_rng(0)
    members = rng.normal(size=(400, 3))
    actual = members @ np.array([0.6, 0.4, 0.0])
    weights = simplex_weights(members, actual)
    assert np.all(weights >= 0) and weights.sum() == pytest.approx(1.0)
    assert weights == pytest.approx([0.6, 0.4, 0.0], abs=1e-6)
    # A member that is better on its own gets all the weight when the others only add noise.
    best = actual + rng.normal(scale=0.01, size=400)
    noisy = np.column_stack([best, best + rng.normal(scale=5, size=400), -best])
    assert simplex_weights(noisy, actual)[0] > 0.99


def test_residual_quantiles_give_the_central_interval():
    low, high = residual_quantiles(np.arange(-50, 51), 0.8)
    assert low == pytest.approx(-40) and high == pytest.approx(40)


def test_training_windows_never_use_weeks_past_the_end():
    series = [np.arange(20.0), np.arange(20.0) * 2]
    inputs, targets = training_windows(series, [1.0, 2.0], input_weeks=8, horizon=4)
    assert inputs.shape == (2 * 9, 8) and targets.shape == (2 * 9, 4)
    assert targets.max() == pytest.approx(19.0)  # the last target is the series' last week, scaled
    assert inputs[0] == pytest.approx(np.arange(8.0))


@pytest.mark.skipif(not HAS_TORCH, reason="PyTorch not installed")
def test_global_lstm_is_deterministic_and_never_negative():
    rng = np.random.default_rng(1)
    series = [np.abs(10 + 5 * np.sin(np.arange(60) / 4 + k) + rng.normal(size=60)) for k in range(5)]
    scales = [float(s.mean()) for s in series]
    settings = LSTMSettings(epochs=3, hidden=8)
    first = GlobalLSTM(settings).fit(series, scales).predict(series, scales)
    second = GlobalLSTM(settings).fit(series, scales).predict(series, scales)
    assert len(first) == 5 and all(len(f) == 4 for f in first)
    assert all(np.all(f >= 0) for f in first)
    assert all(np.allclose(a, b) for a, b in zip(first, second))


@pytest.mark.skipif(not HAS_PROPHET, reason="prophet not installed")
def test_prophet_gives_its_own_80_percent_interval():
    y = 20 + 5 * np.sin(np.arange(80) * 2 * np.pi / 52) + np.random.default_rng(2).normal(size=80)
    model = ProphetForecaster("2024-01-01", uncertainty_samples=100).fit(y)
    mean, lower, upper = model.interval80(4)
    assert len(mean) == 4 and np.all(lower <= mean) and np.all(mean <= upper)
    assert model.clone().name == "Prophet"


def test_prophet_is_a_dashboard_candidate_only_when_installed():
    names = [m.name for m in candidate_models(80, include_statsmodels=False, include_prophet=True)]
    assert "Prophet" in names
    assert "Prophet" not in [m.name for m in candidate_models(80, include_statsmodels=False, include_prophet=False)]
    assert "Prophet" not in [m.name for m in candidate_models(10, include_statsmodels=False, include_prophet=True)]


# ------------------------------------------------------------------ backtest helpers
def test_missing_weeks_are_filled_from_earlier_weeks_only():
    from experiments.forecasting import filled, scale_of

    history = np.array([4.0, np.nan, 8.0, np.nan])
    assert filled(history) == pytest.approx([4.0, 6.0, 8.0, 8.0])  # the trailing gap repeats the last value
    assert scale_of(np.array([0.2, np.nan, 0.4, 100.0]), 3) == 1.0  # at least 1, and only the given weeks


def test_windows_and_scoring_use_common_test_forecasts_and_clip_at_zero():
    from experiments.forecasting import summarise, window_of

    windows = {"validation": [65, 84], "test": [85, 104]}
    assert window_of(64, windows) is None and window_of(65, windows) == "validation" and window_of(104, windows) == "test"
    rows = []
    for model, mean in (("seasonal_naive", 10.0), ("naive", 12.0)):
        for origin in (84, 85):
            rows.append(dict(model=model, series_id="s", origin_week=origin, horizon=1, target_week=origin + 1,
                             window="test", actual=11.0, mean=mean, lower=0.0, upper=11.5))
    rows.append(dict(model="naive", series_id="s", origin_week=90, horizon=1, target_week=91,
                     window="test", actual=11.0, mean=99.0, lower=0.0, upper=1.0))  # no seasonal naive row: not scored
    cfg = {"models": ["seasonal_naive", "naive"], "horizons": [1]}
    summary = summarise(pd.DataFrame(rows), cfg)
    naive = summary[(summary["model"] == "naive") & (summary["horizon"] == "all")].iloc[0]
    assert naive["forecasts"] == 2 and naive["mae"] == pytest.approx(1.0)
    assert naive["mae_ratio_vs_seasonal_naive"] == pytest.approx(1.0)
    assert naive["coverage_80"] == pytest.approx(1.0)  # 11 lies inside [0, 11.5]
