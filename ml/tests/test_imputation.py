"""KNN imputation at the hospital node: fitted on the training split only, never on held-out data."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml.common.datasets import load_local_dataset, save_local_dataset
from ml.ehr import imputation
from ml.ehr.features import EHR_FEATURE_NAMES, NUM_EHR_FEATURES
from ml.ehr.imputation import EHRImputer, MissingnessConfig, impute_splits, simulate_mcar
from ml.training.local_trainer import load_training_splits


def _matrix(n, seed, offset=0.0):
    rng = np.random.default_rng(seed)
    return rng.normal(offset, 1.0, size=(n, NUM_EHR_FEATURES))


def test_simulated_mcar_rate_and_no_empty_rows():
    X = np.ones((2000, NUM_EHR_FEATURES))
    gaps = simulate_mcar(X, 0.10, np.random.default_rng(0))
    assert abs(np.isnan(gaps).mean() - 0.10) < 0.01
    assert not np.isnan(gaps).all(axis=1).any()
    assert not np.isnan(X).any()  # the input is not modified
    heavy = simulate_mcar(np.ones((500, 3)), 0.95, np.random.default_rng(1))
    assert not np.isnan(heavy).all(axis=1).any()


def test_missingness_config_validates():
    assert MissingnessConfig.from_dict(None).mcar_rate == 0.0
    assert MissingnessConfig.from_dict({"mcar_rate": 0.1}).mcar_rate == 0.1
    with pytest.raises(ValueError):
        MissingnessConfig.from_dict({"mcar_rate": 1.0})


def test_imputer_fills_from_training_neighbours_only():
    X_train = np.array([[0.0, 0.0], [0.1, 1.0], [0.2, 2.0], [10.0, 100.0]])
    imputer = EHRImputer(n_neighbors=2).fit(X_train)
    # Nearest training rows to 0.05 are the first two: (0 + 1) / 2.
    assert imputer.transform(np.array([[0.05, np.nan]]))[0, 1] == pytest.approx(0.5)
    # A held-out row that sits next to another held-out row is still filled from training rows.
    held_out = np.array([[9.9, np.nan], [9.95, -500.0]])
    assert imputer.transform(held_out)[0, 1] == pytest.approx((100.0 + 2.0) / 2)


def test_held_out_values_never_change_the_training_split_or_their_own_imputation():
    X_train = simulate_mcar(_matrix(200, 0), 0.1, np.random.default_rng(1))
    X_val = simulate_mcar(_matrix(60, 2), 0.1, np.random.default_rng(3))
    train_a, val_a, report = impute_splits(X_train, X_val)
    # Change every observed held-out value drastically: nothing that came from the training split may move.
    shifted = np.where(np.isnan(X_val), np.nan, X_val + 1000.0)
    train_b, val_b, _ = impute_splits(X_train, shifted)
    np.testing.assert_array_equal(train_a, train_b)
    gaps = np.isnan(X_val)
    # Imputed held-out values are exactly what an imputer fitted on the training split alone gives.
    imputer = EHRImputer().fit(X_train)
    np.testing.assert_allclose(val_a[gaps], imputer.transform(X_val)[gaps], rtol=1e-6)
    assert report["imputation"]["fitted_on"] == "training split"
    assert report["imputation"]["rows"] == 200
    assert not np.isnan(train_a).any() and not np.isnan(val_a).any() and not np.isnan(val_b).any()


def test_impute_splits_fits_on_training_rows_only(monkeypatch):
    seen = []
    original = EHRImputer.fit

    def spy(self, X):
        seen.append(np.array(X, copy=True))
        return original(self, X)

    monkeypatch.setattr(imputation.EHRImputer, "fit", spy)
    X_train, X_val = _matrix(80, 4), _matrix(30, 5, offset=50.0)
    train_out, val_out, report = impute_splits(X_train, X_val, MissingnessConfig(mcar_rate=0.1, seed=7), salt=3)
    assert len(seen) == 1
    assert seen[0].shape == (80, NUM_EHR_FEATURES)
    # Every value the imputer saw is a training value (the held-out rows are centred on 50).
    observed = seen[0][~np.isnan(seen[0])]
    assert np.abs(observed).max() < 10
    assert report["missing_train_values"] > 0 and report["missing_val_values"] > 0


def test_no_gaps_means_no_imputer():
    X = _matrix(20, 6)
    train, val, report = impute_splits(X, X[:5])
    assert report["imputation"] is None
    np.testing.assert_allclose(train, X.astype(np.float32))


def test_simulated_gaps_are_fixed_per_hospital_and_differ_between_hospitals():
    X = _matrix(100, 7)
    config = MissingnessConfig(mcar_rate=0.1, seed=0)
    a1, _, _ = impute_splits(X, X[:10], config, salt=1)
    a2, _, _ = impute_splits(X, X[:10], config, salt=1)
    b, _, _ = impute_splits(X, X[:10], config, salt=2)
    np.testing.assert_array_equal(a1, a2)
    assert not np.array_equal(a1, b)


def _write_hospital(tmp_path, gaps_in_val=True):
    X_train, X_val = _matrix(60, 8) + 5, _matrix(20, 9) + 5
    X_train[0, 2] = np.nan
    if gaps_in_val:
        X_val[1, 3] = np.nan
    y_train, y_val = np.arange(60) % 2, np.arange(20) % 2
    save_local_dataset(tmp_path, "ehr", (X_train, y_train), (X_val, y_val), "custom", "test with gaps")
    return X_train, X_val


def test_node_loader_imputes_real_gaps_with_a_training_split_fit(tmp_path, monkeypatch):
    X_train, _ = _write_hospital(tmp_path)
    # The plain loader still refuses gaps; only the node's training path accepts them.
    with pytest.raises(ValueError, match="missing values"):
        load_local_dataset(tmp_path, "ehr", "train")
    seen = []
    original = EHRImputer.fit
    monkeypatch.setattr(imputation.EHRImputer, "fit", lambda self, X: (seen.append(np.array(X)), original(self, X))[1])
    train, val, report = load_training_splits(tmp_path, "ehr")
    assert len(seen) == 1
    np.testing.assert_allclose(seen[0], X_train.astype(np.float32), equal_nan=True)
    assert not np.isnan(train.X).any() and not np.isnan(val.X).any()
    assert report["missing_train_values"] == 1 and report["missing_val_values"] == 1


def test_a_missing_label_is_still_refused(tmp_path):
    _write_hospital(tmp_path)
    path = tmp_path / "ehr" / "train.csv"
    frame = pd.read_csv(path)
    frame["label"] = frame["label"].astype(float)
    frame.loc[0, "label"] = np.nan
    frame.to_csv(path, index=False)
    with pytest.raises(ValueError, match="label"):
        load_training_splits(tmp_path, "ehr")


def test_feature_names_unchanged():
    assert len(EHR_FEATURE_NAMES) == NUM_EHR_FEATURES


def test_scaled_distances_and_observed_values_kept():
    # Feature 0 is in large units. Unscaled, the nearest rows to [100, 0.0] would be chosen by feature 0;
    # scaled by spread (100, 1), feature 1 decides.
    X_train = np.array([[100.0, 0.0, 1.0], [300.0, 0.05, 2.0], [110.0, 5.0, 50.0], [120.0, 5.1, 60.0]])
    row = np.array([[100.0, 0.0, np.nan]])
    unscaled = EHRImputer(n_neighbors=2).fit(X_train).transform(row)
    scaled = EHRImputer(n_neighbors=2, scale=(np.zeros(3), np.array([100.0, 0.01, 1.0]))).fit(X_train).transform(row)
    assert unscaled[0, 2] == pytest.approx((1.0 + 50.0) / 2)
    assert scaled[0, 2] == pytest.approx((1.0 + 2.0) / 2)
    assert scaled[0, 0] == 100.0 and scaled[0, 1] == 0.0
