"""Isolation Forest screening of incoming updates: flags unusual ones, audits them, never rejects them."""

import numpy as np
import pytest

from app.federated import screening
from backend_test_helpers import run_round
from ml.common.weights import weights_from_bytes, weights_to_bytes


def _w(values):
    return {"layer.weight": np.asarray(values, dtype=np.float32), "bn.running_mean": np.zeros(2, dtype=np.float32)}


def test_features_relative_norm_and_cosine_distance():
    base = _w([0.0, 0.0])
    feats = screening.update_features(base, {"a": _w([1.0, 0.0]), "b": _w([1.0, 0.0]), "c": _w([0.0, 3.0])})
    # Norms 1, 1, 3; median 1. Directions compared with the others' unit-length mean:
    # a vs mean((1, 0), (0, 1)); c vs mean((1, 0), (1, 0)) = (1, 0), at right angles.
    assert feats["c"]["norm"] == pytest.approx(3.0) and feats["c"]["relative_norm"] == pytest.approx(3.0)
    assert feats["a"]["cosine_distance"] == pytest.approx(1 - 1 / np.sqrt(2))
    assert feats["c"]["cosine_distance"] == pytest.approx(1.0)
    # One huge update does not make the others look unusual: their reference direction is their own average.
    big = screening.update_features(base, {"a": _w([1.0, 0.1]), "b": _w([1.0, -0.1]), "c": _w([1.0, 0.0]), "x": _w([0.0, -500.0])})
    assert max(big[h]["cosine_distance"] for h in "abc") < 0.4 and big["x"]["cosine_distance"] > 0.9
    # Batch-norm statistics are not part of the update's size or direction.
    moved_stats = {**_w([1.0, 0.0]), "bn.running_mean": np.array([100.0, 100.0], dtype=np.float32)}
    assert screening.update_features(base, {"a": moved_stats})["a"]["norm"] == pytest.approx(1.0)


def _typical(n, seed=0):
    rng = np.random.default_rng(seed)
    return [{"relative_norm": float(np.exp(rng.normal(0, 0.1))), "cosine_distance": float(abs(rng.normal(0.1, 0.03)))} for _ in range(n)]


def test_not_scored_without_enough_history():
    out = screening.screen({"a": {"norm": 1.0, "relative_norm": 1.0, "cosine_distance": 0.1}}, _typical(screening.MIN_HISTORY - 1))
    assert out["a"]["scored"] is False and out["a"]["flagged"] is False and "needed" in out["a"]["reason"]


def test_outlier_is_flagged_and_typical_updates_are_not():
    current = {
        "a": {"norm": 40.0, "relative_norm": 20.0, "cosine_distance": 1.0},
        "b": {"norm": 1.0, "relative_norm": 1.0, "cosine_distance": 0.1},
        "c": {"norm": 1.0, "relative_norm": 0.95, "cosine_distance": 0.12},
    }
    out = screening.screen(current, _typical(40))
    assert out["a"]["flagged"] and out["a"]["scored"] and "Still used" in out["a"]["reason"]
    assert out["a"]["threshold"] == screening.SCORE_THRESHOLD == 0.6
    # Flagged exactly when the raw score is above the threshold; the score is kept either way.
    assert all(r["flagged"] == (r["score"] > 0.6) for r in out.values())
    assert not out["b"]["flagged"] and not out["c"]["flagged"]
    assert out["a"]["score"] > out["b"]["score"]
    assert screening.screen(current, _typical(40)) == out  # deterministic


def _tampered_round(ctx):
    created = ctx.coordinator.start_round("ehr", ctx.hospitals.list_raw(), "tester", auto_aggregate=False)
    round_id = created["id"]
    for hospital_id in ("hospital_b", "hospital_c", "hospital_d"):
        node = ctx.nodes.node(hospital_id)
        node.train_and_submit(round_id, node.join(round_id))
    # Hospital A trains honestly, then sends its update reversed and five times larger (a poisoning-style update).
    from ml.common.types import TrainConfig
    from ml.training.local_trainer import train_on_local_data

    ctx.coordinator.join(round_id, "hospital_a")
    base = weights_from_bytes(ctx.coordinator.global_model_bytes(round_id, "hospital_a", "base"))
    node = ctx.nodes.node("hospital_a")
    honest = train_on_local_data(node.data_dir, "ehr", base, TrainConfig(2, 32, 0.003, 1), node.backend).weights
    odd = {
        k: (base[k] - 5.0 * (honest[k] - base[k])).astype(base[k].dtype) if np.issubdtype(base[k].dtype, np.floating) else honest[k]
        for k in base
    }
    ctx.coordinator.receive_update(round_id, "hospital_a", weights_to_bytes(odd), 100)
    ctx.coordinator.aggregate(round_id, "tester")
    return round_id


def test_unusual_update_is_flagged_audited_and_still_aggregated(ctx, client):
    from backend_test_helpers import login

    for _ in range(5):  # 20 earlier updates of the EHR model
        assert run_round(ctx, "ehr")["status"] == "COMPLETED"
    round_id = _tampered_round(ctx)

    updates = {u["hospital_id"]: u for u in ctx.coordinator.updates(round_id)}
    assert updates["hospital_a"]["screening"]["flagged"] is True
    assert updates["hospital_a"]["screening"]["history_size"] == 20
    # The poisoned update stands out clearly. Honest updates can also be flagged (non-IID hospitals, little
    # history): the flag is advisory, which is why nothing is rejected on it.
    others = [updates[h]["screening"]["score"] for h in ("hospital_b", "hospital_c", "hospital_d")]
    assert updates["hospital_a"]["screening"]["score"] > max(others) + 0.15
    # Never rejected: the flagged update is aggregated with a FedAvg weight like the others.
    assert all(u["status"] == "AGGREGATED" for u in updates.values())
    assert "hospital_a" in ctx.coordinator.get_round(round_id)["config"]["aggregation"]["coefficients"]

    headers = login(client, "admin@fl-healthcare.demo")
    audit = client.get("/api/audit", params={"action": "UPDATE_FLAGGED_UNUSUAL"}, headers=headers).json()["items"]
    audit = [a for a in audit if a["round_id"] == round_id]
    flagged = {h for h, u in updates.items() if u["screening"]["flagged"]}
    assert {(a["hospital_id"], a["round_id"]) for a in audit} == {(h, round_id) for h in flagged}
    assert all("flag only" in a["details"]["action"] for a in audit)

    detail = client.get(f"/api/federated/rounds/{round_id}", headers=headers).json()
    shown = {p["hospital_id"]: p["screening"] for p in detail["participants"]}
    assert shown["hospital_a"]["flagged"] is True
    assert {h for h, s in shown.items() if s["flagged"]} == flagged


def test_first_rounds_are_not_scored(ctx):
    finished = run_round(ctx, "ehr")
    assert all(u["screening"]["scored"] is False for u in ctx.coordinator.updates(finished["id"]))


def test_hospital_operator_sees_only_its_own_screening(ctx, client):
    from backend_test_helpers import login

    finished = run_round(ctx, "ehr")
    headers = login(client, "hospital_a@fl-healthcare.demo")
    detail = client.get(f"/api/federated/rounds/{finished['id']}", headers=headers)
    assert detail.status_code == 200
    shown = {p["hospital_id"]: p["screening"] for p in detail.json()["participants"]}
    assert shown["hospital_a"] is not None
    assert all(shown[h] is None for h in ("hospital_b", "hospital_c", "hospital_d"))
