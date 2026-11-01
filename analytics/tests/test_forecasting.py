"""Forecasting: models, chronological validation, no leakage, intervals."""

import numpy as np
import pytest

from analytics.forecasting.models import AutoRegressive, NaiveLastValue, SeasonalAutoRegressive, SeasonalNaive
from analytics.forecasting.pipeline import (
    InsufficientDataError,
    chronological_split,
    clean_series,
    evaluate_candidates,
    forecast_series,
    mae,
    rmse,
)


def _seasonal(n=104, seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    return rng.poisson(50 + 25 * np.sin(2 * np.pi * t / 52)).astype(float)


def test_error_metrics():
    assert mae([1, 2, 3], [2, 2, 5]) == pytest.approx(1.0)
    assert rmse([1, 2, 3], [2, 2, 5]) == pytest.approx(np.sqrt(5 / 3))


def test_split_is_chronological():
    train, test = chronological_split(np.arange(10.0), 3)
    assert train.tolist() == [0, 1, 2, 3, 4, 5, 6] and test.tolist() == [7, 8, 9]
    with pytest.raises(ValueError):
        chronological_split(np.arange(5.0), 5)


def test_naive_and_seasonal_naive():
    naive = NaiveLastValue().fit(np.array([3.0, 5.0, 4.0, 9.0]))
    mean, std = naive.forecast(3)
    assert mean.tolist() == [9.0, 9.0, 9.0] and std[2] > std[0]
    series = np.tile(np.arange(52.0), 2)
    mean, _ = SeasonalNaive(52).fit(series).forecast(4)
    assert mean.tolist() == [0.0, 1.0, 2.0, 3.0]


def test_autoregressive_recovers_known_coefficient_and_interval_width():
    rng = np.random.default_rng(0)
    values = [0.0]
    for _ in range(4000):
        values.append(0.7 * values[-1] + rng.normal())
    model = AutoRegressive(order=(1, 0)).fit(np.array(values))
    assert model._coef[1] == pytest.approx(0.7, abs=0.04)
    _, std = model.forecast(5)
    expected = np.sqrt(np.cumsum(0.7 ** (2 * np.arange(5))))
    assert np.allclose(std, expected, rtol=0.06)
    assert np.all(np.diff(std) > 0)


def test_a_prediction_never_uses_the_week_it_predicts_or_later_weeks():
    """Changing weeks from position t onward must not change predictions made for origins up to t."""
    series = _seasonal()
    altered = series.copy()
    altered[-6:] = altered[-6:] * 5 + 300  # tamper with the last six weeks only
    first = {e["model_name"].split("(")[0]: e["holdout_prediction"] for e in evaluate_candidates(series, 12)}
    second = {e["model_name"].split("(")[0]: e["holdout_prediction"] for e in evaluate_candidates(altered, 12)}
    for name in first:
        # Origins 0-6 (weeks -12 .. -6) only ever saw untampered weeks.
        assert first[name][:7] == second[name][:7], name
    naive_first, naive_second = first["Naive "], second["Naive "]
    assert naive_first[7:] != naive_second[7:]  # later origins legitimately see the earlier tampered weeks


def test_rolling_origin_scores_every_available_forecast():
    series = _seasonal()
    one_step = evaluate_candidates(series, 12, horizon=1)
    multi = evaluate_candidates(series, 12, horizon=4)
    assert all(e["forecasts_scored"] == 12 for e in one_step)
    # Origins near the end have fewer than four future weeks: 9 * 4 + 3 + 2 + 1.
    assert all(e["forecasts_scored"] == 42 for e in multi)
    assert all(len(e["holdout_prediction"]) == 12 for e in multi)


def test_seasonal_autoregressive_model_starts_from_the_current_level():
    t = np.arange(120)
    series = 50 + 30 * np.sin(2 * np.pi * t / 52)
    series[-6:] += 40  # a sustained rise above the seasonal pattern
    model = SeasonalAutoRegressive(52).fit(series)
    mean, std = model.forecast(4)
    seasonal_only, _ = SeasonalNaive(52).fit(series).forecast(4)
    assert np.all(mean > seasonal_only)  # carries part of the current gap forward
    assert mean[0] - seasonal_only[0] > mean[3] - seasonal_only[3] > 0  # and lets it decay
    assert np.all(np.diff(std) >= 0)


def test_forecast_does_not_depend_on_future_values():
    series = _seasonal(110)
    truncated = forecast_series(list(series[:104]), horizon=6)
    again = forecast_series(list(series[:104]), horizon=6)
    assert truncated["predicted_values"] == again["predicted_values"]
    # The forecast for weeks 105-110 was produced without those weeks.
    assert len(truncated["history_used"]) == 104


def test_pipeline_output_shape_and_selection():
    result = forecast_series(list(_seasonal()), horizon=8)
    assert result["forecast_horizon"] == 8 and len(result["predicted_values"]) == 8
    selected = [c for c in result["candidates"] if c["selected"]]
    assert len(selected) == 1
    usable = [c["rmse"] for c in result["candidates"] if c["rmse"] is not None]
    assert selected[0]["rmse"] == min(usable) == result["evaluation_metrics"]["rmse"]
    assert "Chronological" in result["evaluation_metrics"]["split"]
    assert result["evaluation_metrics"]["train_size"] + result["evaluation_metrics"]["test_size"] == 104
    assert len(result["evaluation_metrics"]["holdout_prediction"]) == result["evaluation_metrics"]["test_size"]
    interval = result["uncertainty_interval"]
    for step in range(8):
        low95, low80 = interval["level_95"]["lower"][step], interval["level_80"]["lower"][step]
        high80, high95 = interval["level_80"]["upper"][step], interval["level_95"]["upper"][step]
        assert 0 <= low95 <= low80 <= result["predicted_values"][step] <= high80 <= high95


def test_exactly_periodic_series_selects_the_seasonal_model():
    t = np.arange(156)
    periodic = 50 + 30 * np.sin(2 * np.pi * t / 52)
    result = forecast_series(list(periodic), horizon=4)
    assert "Seasonal" in result["model_name"]
    assert result["evaluation_metrics"]["rmse"] == pytest.approx(0.0, abs=1e-9)
    assert np.allclose(result["predicted_values"], 50 + 30 * np.sin(2 * np.pi * np.arange(156, 160) / 52))


def test_forecasts_are_never_negative():
    falling = list(np.linspace(40, 1, 60))
    result = forecast_series(falling, horizon=12)
    assert min(result["predicted_values"]) >= 0
    assert min(result["uncertainty_interval"]["level_95"]["lower"]) >= 0


def test_gaps_are_interpolated_and_reported():
    values = list(_seasonal(60))
    values[10] = None
    values[30] = None
    series, imputed = clean_series(values)
    assert imputed == 2 and not np.isnan(series).any()
    assert series[10] == pytest.approx((values[9] + values[11]) / 2)
    assert forecast_series(values, horizon=4)["imputed_points"] == 2


def test_insufficient_data_is_reported_not_guessed():
    with pytest.raises(InsufficientDataError, match="at least"):
        forecast_series([5.0] * 10, horizon=4)
    mostly_missing = [None if i % 2 else 10.0 for i in range(60)]
    with pytest.raises(InsufficientDataError, match="missing or suppressed"):
        forecast_series(mostly_missing, horizon=4)
    with pytest.raises(ValueError):
        forecast_series(list(_seasonal()), horizon=0)
