"""HTTP API: endpoints, authentication, roles and error handling."""

import io
import json

import numpy as np

from backend_test_helpers import DEMO_PASSWORD, wait_for_round
from ml.common.weights import weights_from_bytes, weights_to_bytes


# ------------------------------------------------------------------- system
def test_health_and_public_config(client):
    assert client.get("/api/health").json()["status"] == "ok"
    config = client.get("/api/system/config").json()
    assert config["demo_mode"] is True
    assert config["auth_provider"] == "demo"
    assert config["simulated_label"] == "SIMULATED / DEMONSTRATION DATA"
    assert set(config["model_backends"]) == {"ehr", "ecg", "xray"}
    assert config["model_backends"]["ehr"]["target_architecture"] == "TabNet"
    accounts = {a["email"]: a for a in config["demo_accounts"]}
    assert {a["role"] for a in accounts.values()} == {
        "admin", "coordinator", "viewer", "hospital", "hospital_manager", "health_officer", "researcher"
    }
    operators = {e: a["hospital_id"] for e, a in accounts.items() if a["role"] == "hospital"}
    assert operators == {f"hospital_{x}@fl-healthcare.demo": f"hospital_{x}" for x in "abcd"}
    assert all(a["hospital_id"] is None for a in accounts.values() if a["role"] not in ("hospital", "hospital_manager"))
    assert accounts["manager_a@fl-healthcare.demo"]["hospital_id"] == "hospital_a"
    assert "password" not in json.dumps(config).lower()


# --------------------------------------------------------------------- auth
def test_endpoints_require_authentication(client):
    for path in (
        "/api/auth/me",
        "/api/hospitals",
        "/api/models",
        "/api/federated/rounds",
        "/api/analytics/overview",
        "/api/audit",
    ):
        response = client.get(path)
        assert response.status_code == 401, path
        assert response.json()["detail"]


def test_invalid_token_is_rejected(client):
    response = client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert response.status_code == 401


def test_login_and_me(client):
    bad = client.post("/api/auth/demo-login", json={"email": "admin@fl-healthcare.demo", "password": "wrong"})
    assert bad.status_code == 401
    good = client.post("/api/auth/demo-login", json={"email": "admin@fl-healthcare.demo", "password": DEMO_PASSWORD})
    assert good.status_code == 200
    token = good.json()["access_token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["email"] == "admin@fl-healthcare.demo" and me["role"] == "admin"


def test_login_is_audited(client, admin):
    entries = client.get("/api/audit", params={"action": "USER_LOGIN"}, headers=admin).json()
    assert entries["total"] >= 1 and entries["items"][0]["actor"] == "admin@fl-healthcare.demo"


def test_viewer_cannot_start_rounds_or_read_audit(client, viewer):
    start = client.post("/api/federated/rounds/start", json={"modality": "ehr"}, headers=viewer)
    assert start.status_code == 403
    assert client.get("/api/audit", headers=viewer).status_code == 403
    assert (
        client.post("/api/hospitals/hospital_a/availability", json={"online": False}, headers=viewer).status_code == 403
    )
    # Read-only pages still work.
    assert client.get("/api/hospitals", headers=viewer).status_code == 200


# ---------------------------------------------------------------- hospitals
def test_hospitals_listing(client, viewer):
    hospitals = client.get("/api/hospitals", headers=viewer).json()
    assert [h["id"] for h in hospitals] == ["hospital_a", "hospital_b", "hospital_c", "hospital_d"]
    first = hospitals[0]
    assert first["online"] is True and first["is_simulated"] is True
    assert set(first["modalities"]) == {"ehr", "ecg", "xray"}
    assert first["data_summary"]["ehr"]["train_samples"] > 0
    assert first["current_round"] is None and first["rounds_completed"] == 0
    # Nothing patient-level is exposed: only counts and provenance.
    assert set(first["data_summary"]["ehr"]) <= {"source", "simulated", "description", "train_samples", "val_samples"}


def test_hospital_detail_metrics_and_404(client, viewer):
    assert client.get("/api/hospitals/hospital_b", headers=viewer).json()["name"]
    metrics = client.get("/api/hospitals/hospital_b/metrics", headers=viewer).json()
    assert metrics["hospital_id"] == "hospital_b" and metrics["participation"] == []
    assert client.get("/api/hospitals/nope", headers=viewer).status_code == 404


def test_availability_toggle(client, coordinator):
    response = client.post("/api/hospitals/hospital_c/availability", json={"online": False}, headers=coordinator)
    assert response.status_code == 200 and response.json()["online"] is False
    assert response.json()["fl_participation"] == "UNAVAILABLE"


# ---------------------------------------------------------------- federated
def test_full_round_through_the_api(client, coordinator):
    started = client.post(
        "/api/federated/rounds/start",
        json={"modality": "ehr", "local_epochs": 1, "learning_rate": 0.005},
        headers=coordinator,
    )
    assert started.status_code == 201, started.text
    body = started.json()
    assert body["status"] in (
        "WAITING_FOR_CLIENTS",
        "TRAINING",
        "UPDATES_RECEIVING",
        "AGGREGATING",
        "EVALUATING",
        "COMPLETED",
    )
    assert body["created_by"] == "coordinator@fl-healthcare.demo"
    assert len(body["participants"]) == 4

    finished = wait_for_round(client, coordinator, body["id"])
    assert finished["status"] == "COMPLETED", finished["error"]
    assert finished["updates_received"] == 4 and finished["evaluations_received"] == 4
    assert finished["result_model_version"] == 1
    assert finished["is_simulated"] is True

    listed = client.get("/api/federated/rounds", headers=coordinator).json()
    assert listed[0]["id"] == body["id"]
    metrics = client.get(f"/api/federated/rounds/{body['id']}/metrics", headers=coordinator).json()
    assert metrics["global_metrics"]["num_samples"] > 0 and len(metrics["local"]) == 8

    model = client.get("/api/models/ehr", headers=coordinator).json()
    assert model["current_version"] == 1 and model["training_status"] == "TRAINED"
    assert [v["version"] for v in model["versions"]] == [1, 0]
    series = client.get("/api/models/ehr/metrics", headers=coordinator).json()
    assert len(series["series"]) == 1 and series["series"][0]["round_id"] == body["id"]
    assert series["dataset"]["simulated"] is True and "held-out" in series["dataset"]["evaluation_split"]
    assert set(series["task"]["metric_definitions"]) >= {"accuracy", "precision", "recall", "f1", "loss"}

    hospital = client.get("/api/hospitals/hospital_a", headers=coordinator).json()
    assert hospital["rounds_completed"] == 1 and hospital["latest_update"]["round_id"] == body["id"]


def test_start_round_validation(client, coordinator):
    assert client.post("/api/federated/rounds/start", json={"modality": "mri"}, headers=coordinator).status_code == 422
    assert (
        client.post(
            "/api/federated/rounds/start", json={"modality": "ehr", "local_epochs": 0}, headers=coordinator
        ).status_code
        == 422
    )
    unknown = client.post(
        "/api/federated/rounds/start", json={"modality": "ehr", "hospital_ids": ["hospital_z"]}, headers=coordinator
    )
    assert unknown.status_code == 404
    dp = client.post(
        "/api/federated/rounds/start",
        json={"modality": "ehr", "differential_privacy": {"enabled": True, "clip_norm": 1.0, "noise_multiplier": 0}},
        headers=coordinator,
    )
    assert dp.status_code == 422 and "noise_multiplier" in dp.json()["detail"]


def test_second_round_for_same_modality_conflicts(client, coordinator):
    body = {"modality": "xray", "auto_aggregate": False}
    first = client.post("/api/federated/rounds/start", json=body, headers=coordinator)
    assert first.status_code == 201
    second = client.post("/api/federated/rounds/start", json=body, headers=coordinator)
    assert second.status_code == 409 and "already in progress" in second.json()["detail"]


def test_unknown_round_is_404(client, coordinator):
    assert client.get("/api/federated/rounds/ehr-r9999", headers=coordinator).status_code == 404
    assert client.post("/api/federated/rounds/ehr-r9999/aggregate", headers=coordinator).status_code == 404


def test_external_node_flow_over_http(client, coordinator, settings, monkeypatch):
    """A hospital node using only the HTTP API: join, download, upload, evaluate."""
    ctx = client.app.state.ctx
    monkeypatch.setattr(ctx, "nodes", None)  # no in-process nodes for this round
    started = client.post(
        "/api/federated/rounds/start",
        json={"modality": "ehr", "hospital_ids": ["hospital_a", "hospital_b"], "min_participants": 2},
        headers=coordinator,
    ).json()
    round_id = started["id"]

    # Node endpoints need the hospital's own token.
    denied = client.post(f"/api/federated/rounds/{round_id}/participate", json={"hospital_id": "hospital_a"})
    assert denied.status_code == 403
    wrong = client.post(
        f"/api/federated/rounds/{round_id}/participate",
        json={"hospital_id": "hospital_a"},
        headers={"X-Hospital-Token": ctx.hospitals.node_token("hospital_b")},
    )
    assert wrong.status_code == 403

    from ml.common.types import TrainConfig
    from ml.registry import get_adapter
    from ml.training.local_trainer import evaluate_on_local_data, train_on_local_data

    for hospital_id in ("hospital_a", "hospital_b"):
        headers = {"X-Hospital-Token": ctx.hospitals.node_token(hospital_id)}
        info = client.post(
            f"/api/federated/rounds/{round_id}/participate",
            json={
                "hospital_id": hospital_id,
                "data_summary": {
                    "ehr": {
                        "source": "simulated",
                        "simulated": True,
                        "train_samples": 10,
                        "val_samples": 5,
                        "patient_names": ["should be dropped"],
                    }
                },
            },
            headers=headers,
        )
        assert info.status_code == 200, info.text
        download = client.get(
            f"/api/federated/rounds/{round_id}/global-model",
            params={"hospital_id": hospital_id, "which": "base"},
            headers=headers,
        )
        assert download.status_code == 200
        global_weights = weights_from_bytes(download.content)
        output = train_on_local_data(
            settings.hospital_data_root / hospital_id, "ehr", global_weights, TrainConfig(local_epochs=1)
        )
        upload = client.post(
            f"/api/federated/rounds/{round_id}/updates",
            data={
                "hospital_id": hospital_id,
                "num_samples": str(output.num_samples),
                "metrics": json.dumps({"training_history": output.history}),
                "architecture_signature": get_adapter("ehr").signature(),
            },
            files={"weights": ("update.npz", io.BytesIO(weights_to_bytes(output.weights)), "application/octet-stream")},
            headers=headers,
        )
        assert upload.status_code == 200, upload.text
        assert upload.json()["status"] == "VALIDATED"

    assert client.get(f"/api/federated/rounds/{round_id}", headers=coordinator).json()["status"] == "EVALUATING"
    stored = client.get("/api/hospitals/hospital_a", headers=coordinator).json()["data_summary"]["ehr"]
    assert "patient_names" not in stored

    for hospital_id in ("hospital_a", "hospital_b"):
        headers = {"X-Hospital-Token": ctx.hospitals.node_token(hospital_id)}
        result = client.get(
            f"/api/federated/rounds/{round_id}/global-model",
            params={"hospital_id": hospital_id, "which": "result"},
            headers=headers,
        )
        evaluation = evaluate_on_local_data(
            settings.hospital_data_root / hospital_id, "ehr", weights_from_bytes(result.content)
        )
        reported = client.post(
            f"/api/federated/rounds/{round_id}/evaluations",
            json={"hospital_id": hospital_id, "evaluation": evaluation.to_dict()},
            headers=headers,
        )
        assert reported.status_code == 200, reported.text

    finished = client.get(f"/api/federated/rounds/{round_id}", headers=coordinator).json()
    assert finished["status"] == "COMPLETED" and finished["result_model_version"] == 1


def test_rejected_upload_returns_422_with_reason(client, coordinator, monkeypatch):
    ctx = client.app.state.ctx
    monkeypatch.setattr(ctx, "nodes", None)
    round_id = client.post("/api/federated/rounds/start", json={"modality": "ehr"}, headers=coordinator).json()["id"]
    headers = {"X-Hospital-Token": ctx.hospitals.node_token("hospital_a")}
    client.post(f"/api/federated/rounds/{round_id}/participate", json={"hospital_id": "hospital_a"}, headers=headers)
    client.get(f"/api/federated/rounds/{round_id}/global-model", params={"hospital_id": "hospital_a"}, headers=headers)
    bogus = weights_to_bytes({"something": np.zeros(3, dtype=np.float32)})
    response = client.post(
        f"/api/federated/rounds/{round_id}/updates",
        data={"hospital_id": "hospital_a", "num_samples": "10"},
        files={"weights": ("update.npz", io.BytesIO(bogus), "application/octet-stream")},
        headers=headers,
    )
    assert response.status_code == 422
    assert "rejected" in response.json()["detail"].lower()


def test_cancel_marks_round_failed(client, coordinator, monkeypatch):
    monkeypatch.setattr(client.app.state.ctx, "nodes", None)
    round_id = client.post("/api/federated/rounds/start", json={"modality": "ecg"}, headers=coordinator).json()["id"]
    cancelled = client.post(f"/api/federated/rounds/{round_id}/cancel", headers=coordinator).json()
    assert cancelled["status"] == "FAILED" and "Cancelled" in cancelled["error"]


# ------------------------------------------------------------------- models
def test_models_before_training(client, viewer):
    models = client.get("/api/models", headers=viewer).json()
    assert [m["id"] for m in models] == ["ehr", "ecg", "xray"]
    for model in models:
        assert model["current_version"] == 0 and model["training_status"] == "NOT_TRAINED"
        assert model["latest_metrics"] is None  # no invented numbers before a round has run
    assert [m["target_architecture"] for m in models] == ["TabNet", "CNN-BiLSTM", "EfficientNet-B3"]
    metrics = client.get("/api/models/ecg/metrics", headers=viewer).json()
    assert metrics["series"] == [] and metrics["latest"] is None
    assert client.get("/api/models/mri", headers=viewer).status_code == 404


# -------------------------------------------------------------------- audit
def test_audit_listing_and_verification(client, coordinator):
    round_id = client.post("/api/federated/rounds/start", json={"modality": "ecg"}, headers=coordinator).json()["id"]
    wait_for_round(client, coordinator, round_id)
    page = client.get("/api/audit", params={"round_id": round_id, "limit": 100}, headers=coordinator).json()
    assert page["total"] == len(page["items"]) > 10
    entry = page["items"][0]
    assert set(entry) >= {
        "timestamp",
        "actor",
        "action",
        "hospital_id",
        "round_id",
        "model_version",
        "status",
        "previous_hash",
        "current_hash",
    }
    assert "FL_ROUND_CREATED" in page["actions"]
    filtered = client.get("/api/audit", params={"search": "aggregation"}, headers=coordinator).json()
    assert filtered["total"] == 2
    verification = client.get("/api/audit/verify", headers=coordinator).json()
    assert verification["valid"] is True and "immutable" in verification["note"]
    assert client.get("/api/audit", params={"limit": 0}, headers=coordinator).status_code == 422
