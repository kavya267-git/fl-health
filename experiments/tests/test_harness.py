"""The experiment harness: partitions, the three methods and the outputs, on a tiny simulated setting."""

import csv
import math

import numpy as np
import pytest

pytest.importorskip("torch")

from experiments import harness  # noqa: E402


@pytest.fixture()
def tiny(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "RESULTS_DIR", tmp_path / "results")
    monkeypatch.setattr(harness, "WORK_DIR", tmp_path / "work")
    config = harness.deep_merge(
        harness.DEFAULTS,
        {
            "name": "tiny",
            "dataset": {"modality": "ecg", "source": "simulated", "scale": 0.2},
            "partition": {"scheme": "dirichlet", "alpha": 1.0},
            "training": {"rounds": 2, "local_epochs": 1},
            "seeds": [0],
            "target_f1": 0.5,
            "variants": [
                {"label": "plain"},
                {"label": "dp", "dp": {"enabled": True, "noise_multiplier": 1.0}, "methods": ["fedavg"]},
            ],
        },
    )
    return config


def test_dirichlet_partition_keeps_every_record_once(tiny, tmp_path):
    partition = harness.build_partition(tiny, 0, tmp_path / "p")
    _, y = harness._pooled_records(tiny["dataset"], 0, tmp_path)
    assert not partition.excluded and len(partition.hospitals) == 4
    assert sum(s["train"] + s["val"] for s in partition.sizes.values()) == len(y)
    per_class = np.sum([np.add(s["train_labels"], s["val_labels"]) for s in partition.sizes.values()], axis=0)
    assert per_class.tolist() == np.bincount(y, minlength=4).tolist()


def test_alpha_infinity_means_an_even_split():
    assert harness._alpha("inf") is None and harness._alpha(float("inf")) is None
    assert harness._alpha(0.1) == 0.1


def test_run_writes_one_row_per_round_and_resumes(tiny):
    out = harness.run_experiment(tiny, log=lambda _: None)
    with (out / "rounds.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    runs = {(r["variant"], r["method"]) for r in rows}
    assert runs == {("plain", "local"), ("plain", "fedavg"), ("plain", "centralised"), ("dp", "fedavg")}
    assert len(rows) == 4 * 2
    fed = [r for r in rows if r["variant"] == "plain" and r["method"] == "fedavg"]
    assert float(fed[0]["upload_bytes_per_hospital"]) > 0 and math.isinf(float(fed[0]["epsilon"]))
    dp = [r for r in rows if r["variant"] == "dp"]
    assert 0 < float(dp[-1]["epsilon"]) < math.inf and float(dp[-1]["epsilon"]) > float(dp[0]["epsilon"])
    for row in rows:
        assert 0.0 <= float(row["macro_f1"]) <= 1.0
        assert {"recall_N", "recall_S", "recall_V", "recall_F"} <= set(row)

    # A second call finds every run done and changes nothing.
    harness.run_experiment(tiny, log=lambda _: None)
    with (out / "rounds.csv").open(newline="") as handle:
        assert len(list(csv.DictReader(handle))) == len(rows)


def test_metric_row_reports_positive_class_for_binary_tasks():
    row = harness.metric_row(np.array([[8, 2], [3, 7]]), "ehr", loss_sum=10.0, n=20)
    assert row["recall_pos"] == pytest.approx(0.7) and row["recall_neg"] == pytest.approx(0.8)
    assert row["f1_pos"] == pytest.approx(2 * 0.7 * 0.7778 / (0.7 + 0.7778), rel=1e-3)
    assert row["macro_f1"] == pytest.approx((row["f1_pos"] + 2 * 0.8 * 0.7273 / (0.8 + 0.7273)) / 2, rel=1e-3)
