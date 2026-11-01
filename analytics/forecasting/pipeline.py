"""Forecast pipeline: clean -> rolling-origin validation -> select -> forecast.

Leakage rules enforced here:

* validation is chronological. For each of the last ``test_size`` weeks (an
  "origin"), every candidate is fitted on the weeks *before* that origin only
  and forecasts the weeks from the origin onward. A prediction for week t
  therefore never uses the value of week t or any later week;
* model orders are chosen inside each fit, on that fit's own training data;
* the model with the lowest pooled error is then refitted on the full history
  to forecast weeks that have not happened yet.

The output is a forecast - a model-based prediction with an uncertainty
interval - never a statement of confirmed future cases.
"""

from __future__ import annotations

from typing import List, Optional, Sequence

import numpy as np

from analytics.forecasting.models import Forecaster, candidate_models

Z_80, Z_95 = 1.2816, 1.9600


class InsufficientDataError(ValueError):
    """The series is too short or too incomplete to forecast."""


def clean_series(values: Sequence[Optional[float]], min_points: int = 30, max_missing_share: float = 0.2):
    """Interpolate short gaps. Returns ``(series, imputed_count)``."""
    series = np.array([np.nan if v is None else float(v) for v in values], dtype=np.float64)
    if len(series) < min_points:
        raise InsufficientDataError(
            f"Only {len(series)} weekly points are available; at least {min_points} are needed."
        )
    missing = np.isnan(series)
    if missing.all():
        raise InsufficientDataError("Every week in this series is missing or suppressed.")
    share = float(missing.mean())
    if share > max_missing_share:
        raise InsufficientDataError(
            f"{share:.0%} of weeks are missing or suppressed; the limit is {max_missing_share:.0%}."
        )
    if missing.any():
        index = np.arange(len(series))
        series[missing] = np.interp(index[missing], index[~missing], series[~missing])
    return series, int(missing.sum())


def mae(actual: np.ndarray, predicted: np.ndarray) -> float:
    return float(np.mean(np.abs(np.asarray(actual) - np.asarray(predicted))))


def rmse(actual: np.ndarray, predicted: np.ndarray) -> float:
    return float(np.sqrt(np.mean((np.asarray(actual) - np.asarray(predicted)) ** 2)))


def chronological_split(series: np.ndarray, test_size: int):
    if test_size < 1 or test_size >= len(series):
        raise ValueError("test_size must be between 1 and len(series) - 1")
    return series[:-test_size], series[-test_size:]


def evaluate_candidates(
    series: np.ndarray,
    test_size: int,
    horizon: int = 1,
    models: Optional[List[Forecaster]] = None,
) -> List[dict]:
    """Rolling-origin evaluation.

    For each origin in the last ``test_size`` weeks the model is fitted on the
    weeks before it and forecasts up to ``horizon`` weeks ahead; errors are
    pooled over every forecast that has an observed value to compare with.
    ``holdout_prediction`` holds the one-week-ahead prediction for each origin.
    """
    series = np.asarray(series, dtype=np.float64)
    n = len(series)
    if test_size < 1 or test_size >= n:
        raise ValueError("test_size must be between 1 and len(series) - 1")
    first_origin = n - test_size
    models = models if models is not None else candidate_models(first_origin)
    results = []
    for model in models:
        errors, one_step, failure = [], [], None
        for origin in range(first_origin, n):
            steps = min(horizon, n - origin)
            try:
                mean, _ = model.clone().fit(series[:origin]).forecast(steps)
            except Exception as exc:  # a candidate that cannot be fitted is reported, not hidden
                failure = str(exc)
                break
            mean = np.clip(mean, 0.0, None)
            if not np.all(np.isfinite(mean)):
                failure = "non-finite forecast"
                break
            errors.extend(mean - series[origin : origin + steps])
            one_step.append(float(mean[0]))
        if failure is not None:
            results.append({"model_name": model.name, "error": failure, "mae": None, "rmse": None})
            continue
        errors = np.asarray(errors)
        fitted_name = model.clone().fit(series[:first_origin]).name
        results.append(
            {
                "model_name": fitted_name,
                "error": None,
                "mae": float(np.mean(np.abs(errors))),
                "rmse": float(np.sqrt(np.mean(errors**2))),
                "forecasts_scored": int(len(errors)),
                "holdout_prediction": one_step,
                "_model": model,
            }
        )
    return results


def forecast_series(
    values: Sequence[Optional[float]],
    horizon: int = 8,
    test_size: Optional[int] = None,
) -> dict:
    """Run the full pipeline on one weekly series."""
    if horizon < 1 or horizon > 26:
        raise ValueError("horizon must be between 1 and 26 weeks")
    series, imputed = clean_series(values)
    test_size = test_size or int(min(12, max(4, len(series) // 5)))

    evaluations = evaluate_candidates(series, test_size, horizon)
    usable = [e for e in evaluations if e["rmse"] is not None]
    if not usable:
        raise InsufficientDataError("No forecasting model could be fitted to this series.")
    best = min(usable, key=lambda e: e["rmse"])

    # The winning model family, refitted on the full history.
    final_model: Forecaster = best["_model"].clone()
    mean, std = final_model.fit(series).forecast(horizon)
    mean = np.clip(mean, 0.0, None)

    def interval(z: float):
        return (
            [float(v) for v in np.clip(mean - z * std, 0.0, None)],
            [float(v) for v in mean + z * std],
        )

    lower80, upper80 = interval(Z_80)
    lower95, upper95 = interval(Z_95)
    return {
        "model_name": final_model.name,
        "forecast_horizon": horizon,
        "predicted_values": [float(v) for v in mean],
        "uncertainty_interval": {
            "level_80": {"lower": lower80, "upper": upper80},
            "level_95": {"lower": lower95, "upper": upper95},
            "method": "Normal approximation from the model's forecast standard error; lower bounds floored at zero.",
        },
        "evaluation_metrics": {
            "mae": best["mae"],
            "rmse": best["rmse"],
            "split": (
                f"Chronological, rolling origin: for each of the last {test_size} weeks the model was fitted on "
                f"the weeks before it only and forecast up to {horizon} week(s) ahead. Errors are pooled over "
                f"{best['forecasts_scored']} forecasts."
            ),
            "test_size": test_size,
            "train_size": len(series) - test_size,
            "forecasts_scored": best["forecasts_scored"],
            "holdout_prediction": best["holdout_prediction"],
        },
        "candidates": [
            {
                "model_name": e["model_name"],
                "mae": e["mae"],
                "rmse": e["rmse"],
                "error": e["error"],
                "selected": e is best,
            }
            for e in evaluations
        ],
        "history_used": [float(v) for v in series],
        "imputed_points": imputed,
    }
