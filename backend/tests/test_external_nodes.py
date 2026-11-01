"""Hospital nodes on separate machines: round deadlines, heartbeats and the start-up check."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.federated import coordinator as rounds
from app.main import create_app
from app.utils.time import utc_now
from ml.registry import get_adapter
from ml.training.node_runner import compatibility_problems, local_architectures

LATER = timedelta(seconds=3600)


def _submit(ctx, round_id, hospital_ids):
    infos = {}
    for hospital_id in hospital_ids:
        node = ctx.nodes.node(hospital_id)
        infos[hospital_id] = node.join(round_id)
        node.train_and_submit(round_id, infos[hospital_id])
    return infos


# ------------------------------------------------------------------ deadline
def test_round_records_its_deadline(ctx):
    created = ctx.coordinator.start_round("ehr", ctx.hospitals.list_raw(), "tester", deadline_seconds=120)
    deadline = created["config"]["deadline"]
    assert deadline["seconds"] == 120 and deadline["training_deadline_at"] and deadline["evaluation_deadline_at"] is None


def test_deadline_out_of_range_is_refused(ctx):
    with pytest.raises(Exception, match="deadline_seconds"):
        ctx.coordinator.start_round("ehr", ctx.hospitals.list_raw(), "tester", deadline_seconds=1)


def test_nothing_happens_before_the_deadline(ctx):
    created = ctx.coordinator.start_round("ehr", ctx.hospitals.list_raw(), "tester")
    _submit(ctx, created["id"], ["hospital_a", "hospital_b"])
    assert ctx.coordinator.enforce_deadlines() == []
    assert ctx.coordinator.get_round(created["id"])["status"] == rounds.UPDATES_RECEIVING


def test_silent_hospital_is_dropped_and_the_round_completes_without_it(ctx):
    created = ctx.coordinator.start_round("ehr", ctx.hospitals.list_raw(), "tester", min_participants=2)
    round_id = created["id"]
    infos = _submit(ctx, round_id, ["hospital_a", "hospital_b", "hospital_c"])  # hospital_d never answers

    assert ctx.coordinator.enforce_deadlines(utc_now() + LATER) == [round_id]
    after = ctx.coordinator.get_round(round_id)
    assert after["status"] == rounds.EVALUATING
    assert after["config"]["deadline"]["evaluation_deadline_at"]
    dropped = {p["hospital_id"]: p for p in ctx.coordinator.participants(round_id)}["hospital_d"]
    assert dropped["status"] == rounds.P_DROPPED and "deadline" in dropped["error"]
    assert set(after["config"]["aggregation"]["coefficients"]) == {"hospital_a", "hospital_b", "hospital_c"}

    for hospital_id, info in infos.items():
        ctx.nodes.node(hospital_id).evaluate_and_report(round_id, info)
    finished = ctx.coordinator.get_round(round_id)
    assert finished["status"] == rounds.COMPLETED
    assert finished["global_metrics"]["evaluated_hospitals"] == ["hospital_a", "hospital_b", "hospital_c"]
    dropped_events = ctx.db.fetch_all(
        "SELECT hospital_id FROM audit_logs WHERE action = 'HOSPITAL_DROPPED' AND round_id = :id", {"id": round_id}
    )
    assert [e["hospital_id"] for e in dropped_events] == ["hospital_d"]


def test_round_fails_at_the_deadline_when_too_few_hospitals_reported(ctx):
    created = ctx.coordinator.start_round("ehr", ctx.hospitals.list_raw(), "tester", min_participants=3)
    round_id = created["id"]
    _submit(ctx, round_id, ["hospital_a"])
    ctx.coordinator.enforce_deadlines(utc_now() + LATER)
    failed = ctx.coordinator.get_round(round_id)
    assert failed["status"] == rounds.FAILED and "deadline" in failed["error"]
    assert ctx.registry.latest("ehr")["version"] == 0


def test_missing_evaluations_are_skipped_at_the_evaluation_deadline(ctx):
    created = ctx.coordinator.start_round("ehr", ctx.hospitals.list_raw(), "tester")
    round_id = created["id"]
    infos = _submit(ctx, round_id, ["hospital_a", "hospital_b", "hospital_c", "hospital_d"])
    assert ctx.coordinator.get_round(round_id)["status"] == rounds.EVALUATING
    for hospital_id in ("hospital_a", "hospital_b"):
        ctx.nodes.node(hospital_id).evaluate_and_report(round_id, infos[hospital_id])

    ctx.coordinator.enforce_deadlines(utc_now() + LATER)
    finished = ctx.coordinator.get_round(round_id)
    assert finished["status"] == rounds.COMPLETED
    statuses = {p["hospital_id"]: p["status"] for p in ctx.coordinator.participants(round_id)}
    assert statuses["hospital_c"] == statuses["hospital_d"] == rounds.P_EVALUATION_FAILED
    # Their updates were averaged, so they still count as training contributors.
    assert len(finished["global_metrics"]["evaluated_hospitals"]) == 2


# ---------------------------------------------------------- external nodes
@pytest.fixture()
def external_client(settings):
    with TestClient(create_app(settings.model_copy(update={"hospital_nodes": "external"}))) as test_client:
        yield test_client


def _beat(hospital_id, **extra):
    return {
        "hospital_id": hospital_id,
        "hostname": "laptop-b",
        "ml_backend": "numpy-reference",
        "device": "cpu",
        "software_version": "1.1.0",
        "data_summary": {"ehr": {"source": "simulated", "simulated": True, "train_samples": 90, "val_samples": 30}},
        **extra,
    }


def _token(client, hospital_id):
    return {"X-Hospital-Token": client.app.state.ctx.hospitals.node_token(hospital_id)}


def _hospitals(client, headers):
    return {h["id"]: h for h in client.get("/api/hospitals", headers=headers).json()}


def test_external_hospitals_are_offline_until_their_node_sends_a_heartbeat(external_client):
    from backend_test_helpers import login

    headers = login(external_client, "admin@fl-healthcare.demo")
    before = _hospitals(external_client, headers)
    assert all(not h["online"] and h["node"] is None and h["node_mode"] == "external" for h in before.values())

    response = external_client.post(
        "/api/federated/node/heartbeat", json=_beat("hospital_b"), headers=_token(external_client, "hospital_b")
    )
    assert response.status_code == 200, response.text
    after = _hospitals(external_client, headers)["hospital_b"]
    assert after["online"] is True
    assert after["node"]["connected"] is True and after["node"]["hostname"] == "laptop-b"
    assert after["node"]["device"] == "cpu" and after["node"]["software_version"] == "1.1.0"
    assert after["data_summary"]["ehr"]["train_samples"] == 90 and after["modalities"] == ["ehr"]


def test_heartbeat_needs_the_hospitals_own_token(external_client):
    wrong = _token(external_client, "hospital_a")
    response = external_client.post("/api/federated/node/heartbeat", json=_beat("hospital_b"), headers=wrong)
    assert response.status_code == 403


def test_a_node_that_stops_beating_is_shown_disconnected(external_client):
    from backend_test_helpers import login

    headers = login(external_client, "admin@fl-healthcare.demo")
    external_client.post("/api/federated/node/heartbeat", json=_beat("hospital_c"), headers=_token(external_client, "hospital_c"))
    stale = (utc_now() - timedelta(seconds=120)).isoformat(timespec="milliseconds")
    external_client.app.state.ctx.db.update("node_heartbeats", {"last_seen_at": stale}, {"hospital_id": "hospital_c"})
    hospital = _hospitals(external_client, headers)["hospital_c"]
    assert hospital["online"] is False and hospital["node"]["connected"] is False
    assert hospital["fl_participation"] == "UNAVAILABLE"


def test_only_connected_external_hospitals_are_invited(external_client):
    from backend_test_helpers import login

    headers = login(external_client, "admin@fl-healthcare.demo")
    for hospital_id in ("hospital_a", "hospital_c"):
        external_client.post(
            "/api/federated/node/heartbeat",
            json=_beat(hospital_id, data_summary={}),
            headers=_token(external_client, hospital_id),
        )
    response = external_client.post("/api/federated/rounds/start", json={"modality": "ehr"}, headers=headers)
    assert response.status_code == 201, response.text
    invited = sorted(p["hospital_id"] for p in response.json()["participants"])
    assert invited == ["hospital_a", "hospital_c"]


def test_availability_toggle_is_refused_for_external_nodes(external_client):
    from backend_test_helpers import login

    headers = login(external_client, "admin@fl-healthcare.demo")
    response = external_client.post("/api/hospitals/hospital_a/availability", json={"online": False}, headers=headers)
    assert response.status_code == 409


def test_system_config_lets_a_node_check_its_model(external_client):
    config = external_client.get("/api/system/config").json()
    assert config["hospital_nodes"] == "external" and config["ml_backend"] == "numpy-reference"
    assert config["model_backends"]["ehr"]["architecture_signature"] == get_adapter("ehr").signature()


# ------------------------------------------------------- start-up check
def _server(hospital_nodes="external", **models):
    return {"hospital_nodes": hospital_nodes, "ml_backend": "numpy-reference", "model_backends": models}


def test_matching_node_passes_the_start_up_check():
    local = local_architectures(["ehr", "ecg"])
    server = _server(**{m: dict(v) for m, v in local.items()})
    assert compatibility_problems(server, local) == []


def test_node_refuses_an_in_process_coordinator():
    local = local_architectures(["ehr"])
    problems = compatibility_problems(_server("in-process", ehr=dict(local["ehr"])), local)
    assert len(problems) == 1 and "HOSPITAL_NODES=external" in problems[0]


def test_node_refuses_a_different_backend_or_architecture():
    local = local_architectures(["ehr"])
    theirs = {"backend": "pytorch", "architecture": "TabNet", "architecture_signature": "x"}
    problems = compatibility_problems(_server(ehr=theirs), local)
    assert len(problems) == 1 and "TabNet (pytorch)" in problems[0]


def test_node_refuses_same_architecture_with_different_layer_shapes():
    local = local_architectures(["ehr"])
    theirs = {**local["ehr"], "architecture_signature": "something-else"}
    problems = compatibility_problems(_server(ehr=theirs), local)
    assert len(problems) == 1 and "different shapes" in problems[0]


def test_node_reports_a_backend_it_cannot_load(monkeypatch):
    monkeypatch.setattr("ml.training.node_runner.get_adapter", _raise_unavailable)
    local = local_architectures(["xray"])
    theirs = {"backend": "pytorch", "architecture": "EfficientNet-B3", "architecture_signature": "x"}
    problems = compatibility_problems(_server(xray=theirs), local)
    assert len(problems) == 1 and "cannot" in problems[0] and "not installed" in problems[0]


def _raise_unavailable(modality):
    from ml.registry import BackendUnavailableError

    raise BackendUnavailableError("ML_BACKEND=pytorch but torch and torchvision is not installed.")
