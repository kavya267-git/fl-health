"""Missing values in EHR data, handled inside the hospital node.

Real records have gaps: a lab test not ordered, a vital sign not charted. A
hospital fills them in before training with k-nearest-neighbour imputation
(each missing value becomes the mean of that feature over the k most similar
training records that have it).

The imputer is fitted on **the hospital's own training split only**. Held-out
records are imputed from training neighbours; they never become neighbours
themselves and never influence how training records are filled. Nothing about
the imputer leaves the hospital.

``simulate_mcar`` blanks a fixed share of values completely at random, so the
pipeline can be exercised on the simulated hospitals, whose generator produces
no gaps. Simulated gaps are a test setting, reported as such, not a property
of the data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

#: Neighbours used to fill a gap (scikit-learn's default).
DEFAULT_NEIGHBOURS = 5


@dataclass(frozen=True)
class MissingnessConfig:
    """Simulated missingness: ``mcar_rate`` of feature values blanked completely at random (0 = off)."""

    mcar_rate: float = 0.0
    seed: int = 0

    def validate(self) -> None:
        if not 0.0 <= self.mcar_rate < 1.0:
            raise ValueError("mcar_rate must be in [0, 1)")

    @classmethod
    def from_dict(cls, payload: Optional[dict]) -> "MissingnessConfig":
        payload = payload or {}
        config = cls(mcar_rate=float(payload.get("mcar_rate", 0.0)), seed=int(payload.get("seed", 0)))
        config.validate()
        return config


def simulate_mcar(X: np.ndarray, rate: float, rng: np.random.Generator) -> np.ndarray:
    """A copy of ``X`` with each value independently set to NaN with probability ``rate``.

    A record never loses every feature: if all of a row's values are drawn, one is kept, chosen at random.
    """
    X = np.array(X, dtype=np.float64, copy=True)
    if rate <= 0 or X.size == 0:
        return X
    mask = rng.random(X.shape) < rate
    full = np.where(mask.all(axis=1))[0]
    if len(full):
        mask[full, rng.integers(0, X.shape[1], size=len(full))] = False
    X[mask] = np.nan
    return X


@dataclass
class EHRImputer:
    """KNN imputation fitted on one hospital's training split."""

    n_neighbors: int = DEFAULT_NEIGHBOURS
    #: Optional (centre, spread) per feature: distances are measured on (x - centre) / spread, so that a
    #: feature in large units does not dominate. Fixed values, not fitted, so nothing leaks from any split.
    scale: Optional[tuple] = None
    #: Number of training rows the imputer was fitted on (for the node's report and the tests).
    fitted_rows: int = 0
    _model: object = field(default=None, repr=False)

    def fit(self, X_train: np.ndarray) -> "EHRImputer":
        from sklearn.impute import KNNImputer

        X_train = self._scaled(np.asarray(X_train, dtype=np.float64))
        if X_train.ndim != 2 or len(X_train) == 0:
            raise ValueError("The imputer needs a non-empty 2-D training matrix")
        all_missing = np.isnan(X_train).all(axis=0)
        if all_missing.any():
            raise ValueError(f"Feature column(s) {np.where(all_missing)[0].tolist()} have no value in the training split")
        # keep_empty_features keeps the column count fixed even in edge cases.
        self._model = KNNImputer(n_neighbors=self.n_neighbors, keep_empty_features=True).fit(X_train)
        self.fitted_rows = len(X_train)
        return self

    def transform(self, X: np.ndarray) -> np.ndarray:
        if self._model is None:
            raise RuntimeError("Fit the imputer on the training split first")
        X = np.asarray(X, dtype=np.float64)
        if not np.isnan(X).any():
            return X.astype(np.float32)
        filled = self._model.transform(self._scaled(X))
        if self.scale is not None:
            centre, spread = (np.asarray(v, dtype=np.float64) for v in self.scale)
            filled = filled * spread + centre
        # Observed values are returned exactly as they were.
        return np.where(np.isnan(X), filled, X).astype(np.float32)

    def _scaled(self, X: np.ndarray) -> np.ndarray:
        if self.scale is None:
            return X
        centre, spread = (np.asarray(v, dtype=np.float64) for v in self.scale)
        return (X - centre) / spread


def impute_splits(
    X_train: np.ndarray,
    X_val: np.ndarray,
    missingness: Optional[MissingnessConfig] = None,
    salt: int = 0,
    n_neighbors: int = DEFAULT_NEIGHBOURS,
    scale: Optional[tuple] = None,
) -> tuple:
    """Simulate gaps (if configured), fit the imputer on the training split, fill both splits.

    ``salt`` makes the simulated gaps differ between hospitals while staying the same in every round for one
    hospital. Returns ``(X_train, X_val, report)``; the report holds counts only.
    """
    missingness = missingness or MissingnessConfig()
    X_train = np.asarray(X_train, dtype=np.float64)
    X_val = np.asarray(X_val, dtype=np.float64)
    if missingness.mcar_rate > 0:
        X_train = simulate_mcar(X_train, missingness.mcar_rate, np.random.default_rng([missingness.seed, salt, 0]))
        X_val = simulate_mcar(X_val, missingness.mcar_rate, np.random.default_rng([missingness.seed, salt, 1]))
    report = {
        "simulated_mcar_rate": missingness.mcar_rate,
        "missing_train_values": int(np.isnan(X_train).sum()),
        "missing_val_values": int(np.isnan(X_val).sum()),
        "imputation": None,
    }
    if not (report["missing_train_values"] or report["missing_val_values"]):
        return X_train.astype(np.float32), X_val.astype(np.float32), report
    imputer = EHRImputer(n_neighbors=n_neighbors, scale=scale).fit(X_train)
    report["imputation"] = {"method": "k-nearest neighbours", "k": n_neighbors, "fitted_on": "training split", "rows": imputer.fitted_rows}
    return imputer.transform(X_train), imputer.transform(X_val), report
