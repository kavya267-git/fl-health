"""Forecasting models for weekly case counts.

Start simple and validated: two naive baselines and an autoregressive model.
Every model implements ``fit(y)`` and ``forecast(h)`` returning a point
forecast and a standard error per step, so they can be compared like for like.

Optional adapters for ``statsmodels`` (full ARIMA) and ``prophet`` are used
when those packages are installed (backend/requirements-optional.txt); neither
is required.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional, Tuple

import numpy as np

#: Standard-normal quantile for a two-sided 80% interval.
Z_80 = 1.2816


class Forecaster(ABC):
    name: str = ""
    min_points: int = 4

    @abstractmethod
    def fit(self, y: np.ndarray) -> "Forecaster": ...

    @abstractmethod
    def forecast(self, horizon: int) -> Tuple[np.ndarray, np.ndarray]:
        """Return ``(mean, standard_error)``, each of length ``horizon``."""

    def clone(self) -> "Forecaster":
        """An unfitted copy with the same configuration."""
        return type(self)()

    def interval80(self, horizon: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """``(mean, lower, upper)`` of the 80% interval; by default mean +/- 1.28 standard errors."""
        mean, std = self.forecast(horizon)
        return mean, mean - Z_80 * std, mean + Z_80 * std


class NaiveLastValue(Forecaster):
    """Next weeks equal the last observed week (random-walk forecast)."""

    name = "Naive (last value)"
    min_points = 3

    def fit(self, y: np.ndarray) -> "NaiveLastValue":
        y = np.asarray(y, dtype=np.float64)
        self._last = float(y[-1])
        diffs = np.diff(y)
        self._sigma = float(np.sqrt(np.mean(diffs**2))) if len(diffs) else 0.0
        return self

    def forecast(self, horizon: int):
        steps = np.arange(1, horizon + 1)
        return np.full(horizon, self._last), self._sigma * np.sqrt(steps)


class SeasonalNaive(Forecaster):
    """Next weeks equal the same weeks one season (52 weeks) earlier."""

    def __init__(self, period: int = 52):
        self.period = period
        self.name = f"Seasonal naive ({period}-week season)"
        self.min_points = period + 2

    def fit(self, y: np.ndarray) -> "SeasonalNaive":
        y = np.asarray(y, dtype=np.float64)
        if len(y) < self.min_points:
            raise ValueError("Series is shorter than one season")
        self._season = y[-self.period :]
        residuals = y[self.period :] - y[: -self.period]
        self._sigma = float(np.sqrt(np.mean(residuals**2)))
        return self

    def clone(self) -> "SeasonalNaive":
        return SeasonalNaive(self.period)

    def forecast(self, horizon: int):
        index = np.arange(horizon)
        mean = self._season[index % self.period]
        cycles = index // self.period + 1
        return mean, self._sigma * np.sqrt(cycles)


class AutoRegressive(Forecaster):
    """ARIMA(p, d, 0): an AR(p) model on the d-times differenced series (d is 0 or 1).

    Coefficients are estimated by conditional least squares. The order (p, d)
    is chosen on an inner, time-ordered validation block cut from the end of
    the training data, so the choice never sees the evaluation period.
    """

    def __init__(self, max_p: int = 4, max_d: int = 1, order: Optional[Tuple[int, int]] = None):
        if max_d not in (0, 1):
            raise ValueError("max_d must be 0 or 1")
        self.max_p = max_p
        self.max_d = max_d
        self.order = order  # fixed (p, d); when None the order is selected in fit()
        self.name = "ARIMA(p,d,0) - least squares"
        self.min_points = 16

    def clone(self) -> "AutoRegressive":
        return AutoRegressive(self.max_p, self.max_d, order=self.order)

    @staticmethod
    def _fit_order(z: np.ndarray, p: int):
        n = len(z)
        rows = n - p
        if rows < p + 3:
            return None
        design = np.ones((rows, p + 1))
        for lag in range(1, p + 1):
            design[:, lag] = z[p - lag : n - lag]
        target = z[p:]
        coef, *_ = np.linalg.lstsq(design, target, rcond=None)
        residuals = target - design @ coef
        sigma2 = float(residuals @ residuals / max(rows - (p + 1), 1))
        return coef, sigma2

    @staticmethod
    def _point_forecast(history: np.ndarray, coef: np.ndarray, p: int, d: int, horizon: int) -> np.ndarray:
        z = list(np.diff(history) if d else history)
        intercept, phi = coef[0], coef[1:]
        steps = []
        for _ in range(horizon):
            value = intercept + sum(phi[lag] * z[-1 - lag] for lag in range(p))
            z.append(value)
            steps.append(value)
        steps = np.asarray(steps)
        return history[-1] + np.cumsum(steps) if d else steps

    def _inner_validation_error(self, y: np.ndarray, p: int, d: int, block: int) -> Optional[float]:
        head, tail = y[:-block], y[-block:]
        fitted = self._fit_order(np.diff(head) if d else head, p)
        if fitted is None:
            return None
        prediction = self._point_forecast(head, fitted[0], p, d, block)
        if not np.all(np.isfinite(prediction)):
            return None
        return float(np.sqrt(np.mean((prediction - tail) ** 2)))

    def fit(self, y: np.ndarray) -> "AutoRegressive":
        y = np.asarray(y, dtype=np.float64)
        if self.order is not None:
            self.p, self.d = self.order
        else:
            block = max(4, len(y) // 6)
            best = None
            for d in range(self.max_d + 1):
                for p in range(1, self.max_p + 1):
                    error = self._inner_validation_error(y, p, d, block)
                    if error is not None and (best is None or error < best[0]):
                        best = (error, p, d)
            if best is None:
                raise ValueError("Series is too short for an autoregressive model")
            _, self.p, self.d = best
        fitted = self._fit_order(np.diff(y) if self.d else y, self.p)
        if fitted is None:
            raise ValueError("Series is too short for an autoregressive model")
        self._coef, self._sigma2 = fitted
        self._history = y.copy()
        self.name = f"ARIMA({self.p},{self.d},0) - least squares"
        return self

    def _psi_weights(self, horizon: int) -> np.ndarray:
        # Combined AR polynomial phi(B) * (1 - B)^d written as 1 - sum(c_k B^k).
        combined = np.concatenate(([1.0], -self._coef[1:]))
        if self.d:
            combined = np.convolve(combined, [1.0, -1.0])
        c = -combined[1:]
        psi = np.zeros(horizon)
        psi[0] = 1.0
        for j in range(1, horizon):
            psi[j] = sum(c[k - 1] * psi[j - k] for k in range(1, min(j, len(c)) + 1))
        return psi

    def forecast(self, horizon: int):
        mean = self._point_forecast(self._history, self._coef, self.p, self.d, horizon)
        psi = self._psi_weights(horizon)
        return mean, np.sqrt(self._sigma2 * np.cumsum(psi**2))


class SeasonalAutoRegressive(Forecaster):
    """Seasonal ARIMA(1,0,0)(0,1,0)[m]: last season's value plus a decaying share of the current gap.

    Let d_t = y_t - y_(t-m) be the difference from the same week one season
    earlier. The model is d_t = phi * d_(t-1) + e_t, so

        forecast(t + h) = y(t + h - m) + phi^h * d_t

    It follows the seasonal shape and starts from the current level instead of
    snapping back to last season's value. ``phi`` is estimated by least squares.
    """

    def __init__(self, period: int = 52):
        self.period = period
        self.name = f"Seasonal ARIMA(1,0,0)(0,1,0)[{period}] - least squares"
        self.min_points = period + 12

    def clone(self) -> "SeasonalAutoRegressive":
        return SeasonalAutoRegressive(self.period)

    def fit(self, y: np.ndarray) -> "SeasonalAutoRegressive":
        y = np.asarray(y, dtype=np.float64)
        if len(y) < self.min_points:
            raise ValueError("Series is too short for the seasonal autoregressive model")
        differences = y[self.period :] - y[: -self.period]
        previous, current = differences[:-1], differences[1:]
        denominator = float(previous @ previous)
        phi = float(previous @ current) / denominator if denominator > 0 else 0.0
        self._phi = float(np.clip(phi, 0.0, 0.98))  # keep the gap decaying, never growing
        residuals = current - self._phi * previous
        self._sigma2 = float(residuals @ residuals / max(len(residuals) - 1, 1))
        self._history = y.copy()
        self._last_gap = float(differences[-1])
        return self

    def forecast(self, horizon: int):
        if horizon > self.period:
            raise ValueError("horizon cannot exceed one season")
        steps = np.arange(1, horizon + 1)
        seasonal = self._history[len(self._history) - self.period + steps - 1]
        mean = seasonal + (self._phi**steps) * self._last_gap
        std = np.sqrt(self._sigma2 * np.cumsum(self._phi ** (2 * (steps - 1))))
        return mean, std


class StatsmodelsARIMA(Forecaster):
    """Optional: full ARIMA(p, d, q) via statsmodels, if it is installed."""

    def __init__(self, order=(2, 1, 1)):
        self.order = order
        self.name = f"ARIMA{order} - statsmodels"
        self.min_points = 20

    def fit(self, y: np.ndarray) -> "StatsmodelsARIMA":
        from statsmodels.tsa.arima.model import ARIMA  # optional dependency

        self._result = ARIMA(np.asarray(y, dtype=np.float64), order=self.order).fit()
        return self

    def clone(self) -> "StatsmodelsARIMA":
        return StatsmodelsARIMA(self.order)

    def forecast(self, horizon: int):
        prediction = self._result.get_forecast(steps=horizon)
        return np.asarray(prediction.predicted_mean), np.asarray(prediction.se_mean)


class ProphetForecaster(Forecaster):
    """Optional: Prophet (piecewise-linear trend plus yearly seasonality), if it is installed.

    Weeks are given dates 7 days apart from ``start`` (an ISO date of the first week); only their spacing and
    position in the year matter. Its 80% interval is Prophet's own (``interval_width`` 0.8).
    """

    def __init__(self, start: str = "2024-01-01", yearly_seasonality: bool = True, uncertainty_samples: int = 300):
        self.start = start
        self.yearly_seasonality = yearly_seasonality
        self.uncertainty_samples = uncertainty_samples
        self.name = "Prophet"
        self.min_points = 20

    def clone(self) -> "ProphetForecaster":
        return ProphetForecaster(self.start, self.yearly_seasonality, self.uncertainty_samples)

    def fit(self, y: np.ndarray) -> "ProphetForecaster":
        import logging

        import pandas as pd
        from prophet import Prophet  # optional dependency

        for name in ("cmdstanpy", "prophet"):
            logging.getLogger(name).setLevel(logging.ERROR)
        y = np.asarray(y, dtype=np.float64)
        frame = pd.DataFrame({"ds": pd.date_range(self.start, periods=len(y), freq="7D"), "y": y})
        self._model = Prophet(
            yearly_seasonality=self.yearly_seasonality,
            weekly_seasonality=False,
            daily_seasonality=False,
            interval_width=0.8,
            uncertainty_samples=self.uncertainty_samples,
        ).fit(frame)
        self._n = len(y)
        return self

    def _predict(self, horizon: int):
        import pandas as pd

        future = pd.DataFrame({"ds": pd.date_range(self.start, periods=self._n + horizon, freq="7D")[self._n :]})
        return self._model.predict(future)

    def interval80(self, horizon: int):
        table = self._predict(horizon)
        return table["yhat"].to_numpy(), table["yhat_lower"].to_numpy(), table["yhat_upper"].to_numpy()

    def forecast(self, horizon: int):
        mean, lower, upper = self.interval80(horizon)
        return mean, (upper - lower) / (2 * Z_80)


def candidate_models(
    n_train: int,
    season: int = 52,
    include_statsmodels: Optional[bool] = None,
    include_prophet: Optional[bool] = None,
    start: Optional[str] = None,
) -> List[Forecaster]:
    """Models that have enough training data to be fitted (optional ones only when installed)."""
    import importlib.util

    candidates: List[Forecaster] = [NaiveLastValue(), AutoRegressive()]
    candidates.extend([SeasonalNaive(season), SeasonalAutoRegressive(season)])
    if include_statsmodels is None:
        include_statsmodels = importlib.util.find_spec("statsmodels") is not None
    if include_statsmodels:
        candidates.append(StatsmodelsARIMA())
    if include_prophet is None:
        include_prophet = importlib.util.find_spec("prophet") is not None
    if include_prophet:
        candidates.append(ProphetForecaster(start) if start else ProphetForecaster())
    return [model for model in candidates if n_train >= model.min_points]
