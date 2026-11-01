"""The hospital node: what it does locally and exactly what it sends out."""

import numpy as np
import pytest

from ml.common.weights import architecture_signature, weights_from_bytes, weights_to_bytes
from ml.reference import build_reference_adapter
from ml.simulation.hospitals import SIMULATED_HOSPITALS, generate_hospital_data
from ml.training.hospital_node import HospitalNode
from ml.training.local_trainer import evaluate_on_local_data


class RecordingTransport:
    """Stands in for the coordinator and records everything the node sends."""

    def __init__(self, modality, dp=None):
        self.adapter = build_reference_adapter(modality)
        self.global_weights = self.adapter.init_weights(0)
        self.modality = modality
        self.dp = dp or {"enabled": False}
        self.calls = []

    def join_round(self, round_id, hospital_id, data_summary):
        self.calls.append(("join", data_summary))
        return {
            "round_id": round_id,
            "modality": self.modality,
            "training": {"local_epochs": 1, "batch_size": 32, "learning_rate": 0.005, "seed": 1},
            "differential_privacy": self.dp,
            "explainability": {"global_importance": True},
        }

    def fetch_global_model(self, round_id, hospital_id, which):
        self.calls.append(("fetch", which))
        return weights_to_bytes(self.global_weights)

    def submit_update(self, round_id, hospital_id, payload, num_samples, metrics, dp_report, signature):
        self.calls.append(("update", payload, num_samples, metrics, dp_report, signature))
        return {"status": "VALIDATED"}

    def submit_evaluation(self, round_id, hospital_id, evaluation, explanation):
        self.calls.append(("evaluation", evaluation, explanation))
        return {"status": "RECORDED"}

    def report_failure(self, round_id, hospital_id, stage, message):
        self.calls.append(("failure", stage, message))


@pytest.fixture(scope="module")
def hospital_dir(tmp_path_factory):
    root = tmp_path_factory.mktemp("node")
    generate_hospital_data(root, SIMULATED_HOSPITALS[0], seed=1, scale=0.2)
    return root / "hospital_a"


def test_join_shares_counts_only(hospital_dir):
    transport = RecordingTransport("ehr")
    HospitalNode("hospital_a", hospital_dir, transport, "numpy-reference").join("r1")
    summary = transport.calls[0][1]
    assert set(summary) == {"ehr", "ecg", "xray"}
    assert set(summary["ehr"]) == {"source", "simulated", "description", "train_samples", "val_samples"}


def test_update_contains_only_weights_counts_and_summary_metrics(hospital_dir):
    transport = RecordingTransport("ehr")
    node = HospitalNode("hospital_a", hospital_dir, transport, "numpy-reference")
    node.train_and_submit("r1", node.join("r1"))
    _, payload, num_samples, metrics, dp_report, signature = next(c for c in transport.calls if c[0] == "update")

    weights = weights_from_bytes(payload)
    assert set(weights) == set(transport.global_weights)  # nothing but the model's own tensors
    assert signature == architecture_signature(weights, "numpy-reference:NumPy reference MLP")
    assert num_samples == 180
    assert any(not np.array_equal(weights[k], transport.global_weights[k]) for k in weights)
    assert set(metrics) == {
        "training_history",
        "local_validation",
        "duration_seconds",
        "dataset_source",
        "backend",
        "architecture",
    }
    assert dp_report["enabled"] is False and dp_report["mechanism"] == "none"
    # The payload is far too small to hide the dataset in: weights only.
    assert len(payload) < 20_000


def test_differential_privacy_clips_the_transmitted_update(hospital_dir):
    dp = {"enabled": True, "clip_norm": 0.05, "noise_multiplier": 1e-6, "delta": 1e-5}
    transport = RecordingTransport("ehr", dp)
    node = HospitalNode("hospital_a", hospital_dir, transport, "numpy-reference")
    node.train_and_submit("r1", node.join("r1"))
    _, payload, _, _, report, _ = next(c for c in transport.calls if c[0] == "update")
    sent = weights_from_bytes(payload)
    norm = np.sqrt(sum(np.sum((sent[k].astype(np.float64) - transport.global_weights[k]) ** 2) for k in sent))
    assert report["clipped"] is True and report["update_norm_before"] > 0.05
    assert norm == pytest.approx(0.05, rel=0.02)


def test_evaluation_reports_sufficient_statistics_and_aggregate_importance(hospital_dir):
    transport = RecordingTransport("ehr")
    node = HospitalNode("hospital_a", hospital_dir, transport, "numpy-reference")
    info = node.join("r1")
    node.evaluate_and_report("r1", info)
    _, evaluation, explanation = next(c for c in transport.calls if c[0] == "evaluation")
    assert set(evaluation) == {"confusion", "loss_sum", "num_samples"}
    assert np.sum(evaluation["confusion"]) == evaluation["num_samples"] == 60
    assert len(explanation["mean_abs"]) == 14 and explanation["num_records"] <= 24
    assert set(explanation) == {"mean_abs", "direction", "num_records", "n_background", "n_permutations", "method"}
    direct = evaluate_on_local_data(hospital_dir, "ehr", transport.global_weights, "numpy-reference")
    assert direct.to_dict()["confusion"] == evaluation["confusion"]


def test_failures_are_reported_to_the_coordinator(tmp_path):
    transport = RecordingTransport("ehr")
    node = HospitalNode("hospital_x", tmp_path / "empty", transport, "numpy-reference")
    with pytest.raises(FileNotFoundError):
        node.run_round("r1")
    assert transport.calls[-1][0] == "failure" and transport.calls[-1][1] == "training"
