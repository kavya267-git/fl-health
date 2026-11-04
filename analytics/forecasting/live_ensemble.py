"""The live ensemble forecast: the protocol of the backtest (experiments/forecasting.py), applied to today's data.

Fixed rules, so nothing is tuned by hand:

* validation window = the ``validation_weeks`` (20) weeks before and including the latest data week;
* every member is refitted at every rolling origin whose 1-4 week forecasts land in that window, on all weeks
  up to the origin, exactly as in the backtest;
* ensemble weights per horizon: non-negative, summing to 1, minimising the squared scaled error of those
  validation forecasts; the 80% likely range: 10th-90th percentiles of the ensemble's scaled validation errors;
* each series is scaled by the mean of its observed weeks before the validation window (at least 1);
* a series is forecast only when at most 20% of its weeks before the validation window are missing;
* the members are then refitted on all weeks, combined with the frozen weights, and clipped at 0.

``run_live_ensemble`` is pure computation; the backend runs it off the request path and stores the result.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional, Sequence

import numpy as np

from analytics.forecasting.ensemble import residual_quantiles, simplex_weights
from analytics.forecasting.lstm import GlobalLSTM, LSTMSettings
from analytics.forecasting.models import (
    AutoRegressive,
    NaiveLastValue,
    ProphetForecaster,
    SeasonalNaive,
    StatsmodelsARIMA,
)

MEMBER_LABELS = {
    "arima_statsmodels": "ARIMA(2,1,1)",
    "prophet": "Prophet",
    "lstm": "LSTM (global)",
    "naive": "Naive (last value)",
    "seasonal_naive": "Seasonal naive",
    "arima_least_squares": "ARIMA(p,d,0)",
}


@dataclass(frozen=True)
class LiveEnsembleConfig:
    members: Sequence[str] = ("arima_statsmodels", "prophet", "lstm")
    validation_weeks: int = 20
    horizons: int = 4
    level: float = 0.8
    max_missing_share: float = 0.2
    lstm: LSTMSettings = field(default_factory=LSTMSettings)
    prophet_uncertainty_samples: int = 300


def _single_series_model(key: str, start: str, config: LiveEnsembleConfig):
    if key == "arima_statsmodels":
        return StatsmodelsARIMA((2, 1, 1))
    if key == "prophet":
        return ProphetForecaster(start, True, config.prophet_uncertainty_samples)
    if key == "naive":
        return NaiveLastValue()
    if key == "seasonal_naive":
        return SeasonalNaive(52)
    if key == "arima_least_squares":
        return AutoRegressive()
    raise ValueError(f"Unknown ensemble member '{key}'")


def _filled(history: np.ndarray) -> np.ndarray:
    """Missing weeks filled from the history itself, never from later weeks."""
    missing = np.isnan(history)
    if not missing.any():
        return history
    index = np.arange(len(history))
    out = history.copy()
    out[missing] = np.interp(index[missing], index[~missing], history[~missing])
    return out


def _member_forecasts(
    members: Sequence[str], histories: Dict[str, np.ndarray], scales: Dict[str, float], start: str, config: LiveEnsembleConfig
) -> Dict[str, Dict[str, np.ndarray]]:
    """{member: {series key: forecast of horizons 1..H}}; a member that cannot fit a series leaves it out."""
    result: Dict[str, Dict[str, np.ndarray]] = {}
    for member in members:
        if member == "lstm":
            keys = list(histories)
            network = GlobalLSTM(config.lstm, horizon=config.horizons).fit(
                [histories[k] for k in keys], [scales[k] for k in keys]
            )
            result[member] = dict(zip(keys, network.predict([histories[k] for k in keys], [scales[k] for k in keys])))
            continue
        result[member] = {}
        for key, history in histories.items():
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    mean, _ = _single_series_model(member, start, config).fit(history).forecast(config.horizons)
            except Exception:  # noqa: BLE001 - reported as a missing forecast, never hidden as a number
                continue
            if np.all(np.isfinite(mean)):
                result[member][key] = np.clip(np.asarray(mean, dtype=float), 0.0, None)
    return result


def run_live_ensemble(
    series: Dict[str, Sequence[Optional[float]]],
    weeks: Sequence[str],
    config: LiveEnsembleConfig = LiveEnsembleConfig(),
    progress: Optional[Callable[[str], None]] = None,
) -> dict:
    """Fit the ensemble on all series at once and forecast ``config.horizons`` weeks past the last week.

    ``series`` maps a key (e.g. "dengue:R01") to weekly counts, oldest first, None where a week has no total.
    """
    say = progress or (lambda _message: None)
    n_weeks = len(weeks)
    first_validation = n_weeks - config.validation_weeks + 1  # 1-based week numbers
    if first_validation <= 1 + config.horizons:
        raise ValueError("Too few weeks for a validation window")
    fit_last = first_validation - 1
    values = {k: np.array([np.nan if v is None else float(v) for v in vs], dtype=float) for k, vs in series.items()}

    eligible, excluded = [], {}
    for key, v in values.items():
        missing = float(np.isnan(v[:fit_last]).mean())
        if missing > config.max_missing_share:
            excluded[key] = f"{missing:.0%} of the weeks before the validation window are missing or suppressed"
        else:
            eligible.append(key)
    if not eligible:
        raise ValueError("No series has enough reported weeks to forecast")

    def scale(key: str, last_week: int) -> float:
        observed = values[key][:last_week]
        observed = observed[~np.isnan(observed)]
        return max(float(observed.mean()) if len(observed) else 1.0, 1.0)

    scales = {k: scale(k, fit_last) for k in eligible}
    rows = []  # (horizon, key, actual, {member: prediction})
    origins = range(first_validation - config.horizons, n_weeks)
    for number, origin in enumerate(origins, start=1):
        histories = {k: _filled(values[k][:origin]) for k in eligible}
        origin_scales = {k: scale(k, min(origin, fit_last)) for k in eligible}
        forecasts = _member_forecasts(config.members, histories, origin_scales, weeks[0], config)
        for h in range(1, config.horizons + 1):
            target = origin + h
            if not first_validation <= target <= n_weeks:
                continue
            for key in eligible:
                actual = values[key][target - 1]
                if np.isnan(actual) or any(key not in forecasts[m] for m in config.members):
                    continue
                rows.append((h, key, actual, {m: float(forecasts[m][key][h - 1]) for m in config.members}))
        say(f"validation origin {number} of {len(origins)}")

    weights, quantiles, validation = {}, {}, {}
    for h in range(1, config.horizons + 1):
        at_h = [r for r in rows if r[0] == h]
        if not at_h:
            raise ValueError(f"No validation forecasts at horizon {h}")
        member_matrix = np.array([[r[3][m] / scales[r[1]] for m in config.members] for r in at_h])
        actual_scaled = np.array([r[2] / scales[r[1]] for r in at_h])
        w = simplex_weights(member_matrix, actual_scaled)
        combined = np.clip(member_matrix @ w, 0.0, None)
        weights[h] = {m: float(x) for m, x in zip(config.members, w)}
        quantiles[h] = residual_quantiles(actual_scaled - combined, config.level)
        raw_actual = np.array([r[2] for r in at_h])
        raw_scale = np.array([scales[r[1]] for r in at_h])
        validation[h] = {
            "forecasts": len(at_h),
            "ensemble_mae": float(np.mean(np.abs(raw_actual - combined * raw_scale))),
            **{
                f"{m}_mae": float(np.mean(np.abs(raw_actual - np.array([r[3][m] for r in at_h])))) for m in config.members
            },
        }

    say("final fit on all weeks")
    histories = {k: _filled(values[k]) for k in eligible}
    final = _member_forecasts(config.members, histories, {k: scale(k, fit_last) for k in eligible}, weeks[0], config)
    forecasts = {}
    for key in eligible:
        if any(key not in final[m] for m in config.members):
            excluded[key] = "a member model could not be fitted to this series"
            continue
        points = []
        for h in range(1, config.horizons + 1):
            mean = max(sum(weights[h][m] * final[m][key][h - 1] for m in config.members), 0.0)
            q_low, q_high = quantiles[h]
            points.append(
                {
                    "horizon": h,
                    "predicted": mean,
                    "lower": max(mean + q_low * scales[key], 0.0),
                    "upper": max(mean + q_high * scales[key], 0.0),
                }
            )
        forecasts[key] = points

    return {
        "members": list(config.members),
        "member_labels": {m: MEMBER_LABELS.get(m, m) for m in config.members},
        "weights": {str(h): w for h, w in weights.items()},
        "validation": {str(h): v for h, v in validation.items()},
        "validation_window": {"first_week": weeks[first_validation - 1], "last_week": weeks[-1], "weeks": config.validation_weeks},
        "data_through": weeks[-1],
        "level": config.level,
        "forecasts": forecasts,
        "excluded": excluded,
    }
