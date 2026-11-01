"""Round lifecycle at the service level."""

import numpy as np
import pytest

from analytics.privacy.dp import DPConfig
from app.federated import coordinator as rounds
from app.utils.errors import ConflictError, PermissionDenied, ValidationFailed
from backend_test_helpers import run_round
from ml.common.weights import weights_from_bytes, weights_to_bytes
from ml.registry import get_adapter


def test_round_completes_and_registers_a_new_global_model(ctx):
    before = ctx.registry.latest("ehr")
    assert before["version"] == 0 and before["status"] == "INITIAL"

    finished = run_round(ctx, "ehr")

    assert finished["status"] == rounds.COMPLETED
    assert finished["aggregation_status"] == "COMPLETED"
    assert finished["result_model_version"] == 1
    assert finished["ended_at"] is not None
    metrics = finished["global_metrics"]
    for key in ("accuracy", "precision", "recall", "f1", "loss", "num_samples", "confusion"):
        assert key in metrics
    assert 0.0 <= metrics["accuracy"] <= 1.0

    after = ctx.registry.latest("ehr")
    assert after["version"] == 1 and after["status"] == "ACTIVE" and after["round_id"] == finished["id"]
    assert after["weights_sha256"] != before["weights_sha256"]

    participants = ctx.coordinator.participants(finished["id"])
    assert len(participants) == 4
    assert all(p["status"] == rounds.P_EVALUATED for p in participants)
    assert all(p["num_samples"] > 0 for p in participants)


def test_global_model_is_the_sample_weighted_average_of_updates(ctx):
    """Recompute FedAvg by hand from what each hospital trains and compare."""
    created = ctx.coordinator.start_round("ehr", ctx.hospitals.list_raw(), "tester", auto_aggregate=False)
    round_id = created["id"]
    sent = {}

    class Recording(type(ctx.nodes.transport)):
        def submit_update(self, round_id, hospital_id, payload, num_samples, *args):
            sent[hospital_id] = (weights_from_bytes(payload), num_samples)
            return super().submit_update(round_id, hospital_id, payload, num_samples, *args)

    ctx.nodes.transport = Recording(ctx.coordinator)
    for hospital in ctx.hospitals.list_raw():
        node = ctx.nodes.node(hospital["id"])
        node.train_and_submit(round_id, node.join(round_id))
    assert ctx.coordinator.get_round(round_id)["status"] == rounds.UPDATES_RECEIVING

    ctx.coordinator.aggregate(round_id, "tester")
    aggregated = weights_from_bytes(ctx.coordinator.global_model_bytes(round_id, "hospital_a", "result"))

    total = sum(n for _, n in sent.values())
    for key in aggregated:
        expected = sum(weights[key].astype(np.float64) * n / total for weights, n in sent.values())
        assert np.allclose(aggregated[key], expected, atol=1e-6)


def test_modalities_keep_separate_registries(ctx):
    run_round(ctx, "ehr")
    run_round(ctx, "ecg")
    assert ctx.registry.latest("ehr")["version"] == 1
    assert ctx.registry.latest("ecg")["version"] == 1
    assert ctx.registry.latest("xray")["version"] == 0
    signatures = {m: ctx.registry.latest(m)["architecture_signature"] for m in ("ehr", "ecg", "xray")}
    assert len(set(signatures.values())) == 3


def test_next_round_starts_from_the_previous_global_model(ctx):
    first = run_round(ctx, "ecg")
    second = run_round(ctx, "ecg")
    assert second["base_model_version"] == first["result_model_version"] == 1
    assert second["result_model_version"] == 2
    assert second["round_number"] == 2


def test_only_one_active_round_per_modality(ctx):
    ctx.coordinator.start_round("ehr", ctx.hospitals.list_raw(), "tester")
    with pytest.raises(ConflictError):
        ctx.coordinator.start_round("ehr", ctx.hospitals.list_raw(), "tester")
    # A different modality is independent.
    assert (
        ctx.coordinator.start_round("ecg", ctx.hospitals.list_raw(), "tester")["status"] == rounds.WAITING_FOR_CLIENTS
    )


def test_offline_hospitals_are_not_selected(ctx):
    ctx.hospitals.set_online("hospital_d", False, "tester")
    finished = run_round(ctx, "ehr")
    ids = [p["hospital_id"] for p in ctx.coordinator.participants(finished["id"])]
    assert ids == ["hospital_a", "hospital_b", "hospital_c"]
    assert finished["status"] == rounds.COMPLETED


def test_round_needs_enough_online_hospitals(ctx):
    for hospital_id in ("hospital_b", "hospital_c", "hospital_d"):
        ctx.hospitals.set_online(hospital_id, False, "tester")
    with pytest.raises(ConflictError):
        ctx.coordinator.start_round("ehr", ctx.hospitals.list_raw(), "tester", min_participants=2)


def test_update_from_another_architecture_is_rejected(ctx):
    created = ctx.coordinator.start_round("ehr", ctx.hospitals.list_raw(), "tester")
    round_id = created["id"]
    ctx.coordinator.join(round_id, "hospital_a")
    ctx.coordinator.global_model_bytes(round_id, "hospital_a", "base")
    wrong = weights_to_bytes(get_adapter("ecg").init_weights(0))

    with pytest.raises(ValidationFailed) as error:
        ctx.coordinator.receive_update(round_id, "hospital_a", wrong, 100)
    assert "architecture" in error.value.message.lower()

    participant = next(p for p in ctx.coordinator.participants(round_id) if p["hospital_id"] == "hospital_a")
    assert participant["status"] == rounds.P_REJECTED
    update = ctx.coordinator.updates(round_id)[0]
    assert update["status"] == "REJECTED" and update["rejection_reason"]


def test_update_with_nan_is_rejected(ctx):
    created = ctx.coordinator.start_round("ehr", ctx.hospitals.list_raw(), "tester")
    round_id = created["id"]
    ctx.coordinator.join(round_id, "hospital_a")
    weights = weights_from_bytes(ctx.coordinator.global_model_bytes(round_id, "hospital_a", "base"))
    weights["W1"][0, 0] = np.nan
    with pytest.raises(ValidationFailed):
        ctx.coordinator.receive_update(round_id, "hospital_a", weights_to_bytes(weights), 100)


def test_garbage_payload_is_rejected(ctx):
    created = ctx.coordinator.start_round("ehr", ctx.hospitals.list_raw(), "tester")
    ctx.coordinator.join(created["id"], "hospital_a")
    ctx.coordinator.global_model_bytes(created["id"], "hospital_a", "base")
    with pytest.raises(ValidationFailed):
        ctx.coordinator.receive_update(created["id"], "hospital_a", b"not a weights archive", 100)


def test_hospital_outside_the_round_cannot_submit(ctx):
    selected = [h for h in ctx.hospitals.list_raw() if h["id"] != "hospital_d"]
    created = ctx.coordinator.start_round("ehr", selected, "tester")
    with pytest.raises(PermissionDenied):
        ctx.coordinator.join(created["id"], "hospital_d")


def test_round_survives_one_failed_hospital(ctx):
    created = ctx.coordinator.start_round("ehr", ctx.hospitals.list_raw(), "tester", min_participants=2)
    round_id = created["id"]
    ctx.coordinator.join(round_id, "hospital_a")
    ctx.coordinator.report_failure(round_id, "hospital_a", "training", "disk full")
    ctx.nodes.run_round(round_id)
    finished = ctx.coordinator.get_round(round_id)
    assert finished["status"] == rounds.COMPLETED
    statuses = {p["hospital_id"]: p["status"] for p in ctx.coordinator.participants(round_id)}
    assert statuses["hospital_a"] == rounds.P_FAILED
    assert finished["global_metrics"]["evaluated_hospitals"] == ["hospital_b", "hospital_c", "hospital_d"]


def test_round_fails_when_too_few_hospitals_remain(ctx):
    created = ctx.coordinator.start_round("ehr", ctx.hospitals.list_raw(), "tester", min_participants=4)
    round_id = created["id"]
    ctx.coordinator.join(round_id, "hospital_a")
    ctx.coordinator.report_failure(round_id, "hospital_a", "training", "out of memory")
    failed = ctx.coordinator.get_round(round_id)
    assert failed["status"] == rounds.FAILED
    assert "required" in failed["error"]
    # The registry is untouched by a failed round.
    assert ctx.registry.latest("ehr")["version"] == 0


def test_manual_aggregation_drops_hospitals_that_did_not_report(ctx):
    created = ctx.coordinator.start_round("ehr", ctx.hospitals.list_raw(), "tester", auto_aggregate=False)
    round_id = created["id"]
    for hospital_id in ("hospital_a", "hospital_b"):
        node = ctx.nodes.node(hospital_id)
        node.train_and_submit(round_id, node.join(round_id))
    aggregated = ctx.coordinator.aggregate(round_id, "tester")
    assert aggregated["status"] == rounds.EVALUATING
    statuses = {p["hospital_id"]: p["status"] for p in ctx.coordinator.participants(round_id)}
    assert statuses["hospital_c"] == rounds.P_DROPPED and statuses["hospital_d"] == rounds.P_DROPPED
    coefficients = aggregated["config"]["aggregation"]["coefficients"]
    assert set(coefficients) == {"hospital_a", "hospital_b"}
    assert abs(sum(coefficients.values()) - 1.0) < 1e-9


def test_aggregation_requires_minimum_updates(ctx):
    created = ctx.coordinator.start_round("ehr", ctx.hospitals.list_raw(), "tester", auto_aggregate=False)
    with pytest.raises(ConflictError):
        ctx.coordinator.aggregate(created["id"], "tester")


def test_interrupted_rounds_are_failed_on_restart(ctx):
    created = ctx.coordinator.start_round("ehr", ctx.hospitals.list_raw(), "tester")
    assert ctx.coordinator.recover_interrupted("restart") == 1
    assert ctx.coordinator.get_round(created["id"])["status"] == rounds.FAILED


def test_differential_privacy_round_reports_clipping_and_noise(ctx):
    finished = run_round(ctx, "ehr", dp=DPConfig(enabled=True, clip_norm=0.5, noise_multiplier=0.01))
    assert finished["status"] == rounds.COMPLETED
    for update in ctx.coordinator.updates(finished["id"]):
        report = update["dp_report"]
        assert report["enabled"] and report["mechanism"] == "gaussian"
        assert report["noise_std"] == pytest.approx(0.005)
        assert report["prototype"] is True


def test_metrics_are_recorded_for_local_and_global_scopes(ctx):
    finished = run_round(ctx, "ehr")
    metrics = ctx.coordinator.round_metrics(finished["id"])
    assert len([m for m in metrics["local"] if m["split"] == "train"]) == 4
    assert len([m for m in metrics["local"] if m["split"] == "val"]) == 4
    assert len(metrics["global_per_hospital"]) == 4
    pooled = sum(m["num_samples"] for m in metrics["global_per_hospital"])
    assert pooled == metrics["global_metrics"]["num_samples"]


def test_weight_files_are_pruned_but_metadata_is_kept(ctx):
    for _ in range(ctx.settings.model_keep_versions + 2):
        run_round(ctx, "ecg")
    versions = ctx.registry.versions("ecg")
    assert len(versions) == ctx.settings.model_keep_versions + 3  # including version 0
    assert sum(1 for v in versions if v["weights_path"]) == ctx.settings.model_keep_versions
    assert versions[0]["weights_path"] is not None  # newest is always loadable


def test_coordinator_storage_holds_no_update_files_after_completion(ctx):
    finished = run_round(ctx, "ehr")
    assert not (ctx.settings.model_storage_path / "rounds" / finished["id"]).exists()
    assert all(u["storage_path"] is None for u in ctx.coordinator.updates(finished["id"]))
