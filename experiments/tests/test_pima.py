"""Experiment 1g (PIMA): data handling, partition, preprocessing and metrics. No training here."""

from __future__ import annotations

import numpy as np
import pytest

from experiments import pima

ARFF = """% comment
@relation pima_diabetes
@attribute 'preg' real
@attribute 'plas' real
@attribute 'pres' real
@attribute 'skin' real
@attribute 'insu' real
@attribute 'mass' real
@attribute 'pedi' real
@attribute 'age' real
@attribute 'class' { tested_negative, tested_positive}
@data
6,148,72,35,0,33.6,0.627,50,tested_positive
1,85,66,29,0,26.6,0.351,31,tested_negative
8,183,64,0,0,23.3,0.672,32,tested_positive
"""


@pytest.fixture()
def config():
    return pima.load_config()


def test_protocol_is_the_fixed_one(config):
    assert config["partition"] == {
        "scheme": "dirichlet", "alpha": 1.0, "partition_seed": 0, "val_fraction": 0.25,
        "hospitals": ["hospital_a", "hospital_b", "hospital_c", "hospital_d"], "min_train_records": 8,
    }
    assert config["seeds"] == [0, 1, 2]
    assert config["methods"]["random_forest"] == ["local", "centralised"]
    assert config["methods"]["gradient_boosting"] == ["local", "centralised"]
    assert "fedavg" in config["methods"]["tabnet"] and "fedavg" in config["methods"]["logistic_regression"]


def test_read_arff_and_zeros_as_missing(tmp_path, config):
    path = tmp_path / "d.arff"
    path.write_text(ARFF, encoding="utf-8")
    X, y = pima.read_arff(path)
    assert X.shape == (3, 8) and y.tolist() == [1, 0, 1]
    marked, counts = pima.mark_missing(X, config)
    assert counts == {"plas": 0, "pres": 0, "skin": 1, "insu": 3, "mass": 0}
    assert np.isnan(marked[2, pima.FEATURES.index("skin")])
    # Pregnancies of 0 are real values, never marked.
    assert "preg" not in config["dataset"]["missing_if_zero"]


def test_download_is_checked_against_the_published_md5(tmp_path, monkeypatch, config):
    path = tmp_path / "d.arff"
    path.write_text(ARFF, encoding="utf-8")
    monkeypatch.setenv("PIMA_ARFF", str(path))
    with pytest.raises(ValueError, match="MD5"):
        pima.fetch(config)


def test_partition_is_fixed_and_disjoint(config):
    y = np.array([0] * 500 + [1] * 268)
    a, b = pima.make_partition(y, config), pima.make_partition(y, config)
    rows = []
    for h in config["partition"]["hospitals"]:
        if "excluded" in a[h]:
            continue
        np.testing.assert_array_equal(a[h]["train"], b[h]["train"])
        np.testing.assert_array_equal(a[h]["val"], b[h]["val"])
        assert not set(a[h]["train"]) & set(a[h]["val"])
        rows += list(a[h]["train"]) + list(a[h]["val"])
    assert len(rows) == len(set(rows))


def test_preprocessor_uses_the_training_split_only():
    rng = np.random.default_rng(0)
    X_train = rng.normal(0, 1, size=(50, 8))
    X_train[0, 3] = np.nan
    X_val = rng.normal(100, 1, size=(10, 8))
    X_val[0, 4] = np.nan
    pre = pima.Preprocessor(X_train, k=5)
    np.testing.assert_allclose(pre.mean, np.nanmean(X_train, axis=0))
    out = pre(X_val)
    assert not np.isnan(out).any()
    # The gap in a held-out row is filled from training rows (around 0), not from the held-out rows (around 100).
    filled = out[0, 4] * pre.std[4] + pre.mean[4]
    assert abs(filled) < 5
    # Refitting with different held-out data changes nothing for the training split.
    np.testing.assert_allclose(pre(X_train), pima.Preprocessor(X_train, k=5)(X_train))


def test_scores_and_reliability():
    y = np.array([0, 0, 1, 1])
    p = np.array([0.1, 0.6, 0.4, 0.9])
    s = pima.scores(y, p, 0.5)
    assert s["roc_auc"] == pytest.approx(0.75)
    assert s["recall"] == pytest.approx(0.5) and s["f1"] == pytest.approx(0.5)
    assert s["brier"] == pytest.approx((0.01 + 0.36 + 0.36 + 0.01) / 4)
    bins = pima.reliability(y, p, 2)
    assert [b["n"] for b in bins] == [2, 2]
    assert bins[0]["observed"] == pytest.approx(0.5) and bins[1]["mean_predicted"] == pytest.approx(0.75)


def test_models_build_with_eight_inputs():
    for adapter in (pima.PimaTabNetAdapter(), pima.PimaLogisticAdapter()):
        weights = adapter.init_weights(0)
        proba = adapter.predict_proba(weights, np.zeros((3, 8), dtype=np.float32))
        assert proba.shape == (3, 2)


def test_rank_auc_matches_scikit_learn_including_ties():
    from sklearn.metrics import roc_auc_score

    rng = np.random.default_rng(3)
    for _ in range(20):
        y = rng.integers(0, 2, 60)
        p = np.round(rng.random(60), 1)  # many ties
        assert pima._auc(y, p) == pytest.approx(roc_auc_score(y, p))
    assert np.isnan(pima._auc(np.ones(5, dtype=int), np.linspace(0, 1, 5)))
