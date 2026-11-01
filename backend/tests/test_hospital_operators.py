"""Hospital operators: what they may see and do, enforced by the API, and the participation switch."""

import pytest

from backend_test_helpers import login, wait_for_round

OPERATOR_A = "hospital_a@fl-healthcare.demo"


@pytest.fixture()
def operator(client) -> dict:
    return login(client, OPERATOR_A)


def _audit(client, headers, action):
    return client.get("/api/audit", params={"action": action, "limit": 50}, headers=headers).json()["items"]


# ------------------------------------------------------------- accounts
def test_demo_operator_signs_in_linked_to_its_hospital(client, operator):
    me = client.get("/api/auth/me", headers=operator).json()
    assert me["role"] == "hospital" and me["hospital_id"] == "hospital_a"


def test_admin_assigns_the_hospital_role_with_a_hospital(client, admin):
    created = client.post(
        "/api/auth/register", json={"email": "nurse@example.org", "password": "long-enough-1", "display_name": "Nurse"}
    ).json()["user"]
    url = f"/api/users/{created['id']}/role"

    missing = client.post(url, json={"role": "hospital"}, headers=admin)
    assert missing.status_code == 422 and "hospital" in missing.json()["detail"]
    unknown = client.post(url, json={"role": "hospital", "hospital_id": "hospital_z"}, headers=admin)
    assert unknown.status_code == 422

    assigned = client.post(url, json={"role": "hospital", "hospital_id": "hospital_c"}, headers=admin)
    assert assigned.status_code == 200 and assigned.json()["hospital_id"] == "hospital_c"
    nurse = login_with(client, "nurse@example.org", "long-enough-1")
    assert client.get("/api/my-hospital", headers=nurse).json()["hospital"]["id"] == "hospital_c"

    # Any other role unlinks the hospital.
    back = client.post(url, json={"role": "viewer", "hospital_id": "hospital_c"}, headers=admin)
    assert back.json()["role"] == "viewer" and back.json()["hospital_id"] is None
    changes = _audit(client, admin, "USER_ROLE_CHANGED")
    assert any(e["details"].get("hospital_to") == "hospital_c" for e in changes)


def login_with(client, email, password):
    response = client.post("/api/auth/demo-login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_only_an_admin_can_make_someone_a_hospital_operator(client, coordinator):
    users = client.get("/api/users", headers=coordinator)
    assert users.status_code == 403


# ---------------------------------------------------------- permissions
def test_operator_reads_general_dashboards_like_a_viewer(client, operator):
    for path in ("/api/hospitals", "/api/federated/rounds", "/api/models", "/api/analytics/overview"):
        assert client.get(path, headers=operator).status_code == 200, path


def test_operator_sees_detailed_pages_of_its_own_hospital_only(client, operator):
    assert client.get("/api/hospitals/hospital_a", headers=operator).status_code == 200
    assert client.get("/api/hospitals/hospital_a/metrics", headers=operator).status_code == 200
    for path in ("/api/hospitals/hospital_b", "/api/hospitals/hospital_b/metrics"):
        response = client.get(path, headers=operator)
        assert response.status_code == 403 and "own hospital" in response.json()["detail"]


def test_operator_cannot_start_rounds_or_read_the_audit_log(client, operator):
    assert client.post("/api/federated/rounds/start", json={"modality": "ehr"}, headers=operator).status_code == 403
    assert client.get("/api/audit", headers=operator).status_code == 403
    assert client.get("/api/audit/verify", headers=operator).status_code == 403
    assert client.post("/api/hospitals/hospital_a/availability", json={"online": False}, headers=operator).status_code == 403


def test_my_hospital_is_for_operators_only(client, operator, viewer, admin):
    page = client.get("/api/my-hospital", headers=operator)
    assert page.status_code == 200
    body = page.json()
    assert body["hospital"]["id"] == "hospital_a" and body["latest_round"] is None
    assert body["hospital"]["participating"] is True
    assert client.get("/api/my-hospital", headers=viewer).status_code == 403
    assert client.get("/api/my-hospital", headers=admin).status_code == 403


def test_operator_sees_every_hospital_progress_but_only_its_own_results(client, operator, admin):
    started = client.post("/api/federated/rounds/start", json={"modality": "ehr"}, headers=admin).json()
    finished = wait_for_round(client, admin, started["id"])
    assert finished["status"] == "COMPLETED"

    seen = client.get(f"/api/federated/rounds/{started['id']}", headers=operator).json()
    by_hospital = {p["hospital_id"]: p for p in seen["participants"]}
    assert set(by_hospital) == {"hospital_a", "hospital_b", "hospital_c", "hospital_d"}
    assert all(p["status"] == "EVALUATED" for p in by_hospital.values())
    assert by_hospital["hospital_a"]["local_metrics"] is not None
    assert all(by_hospital[h]["local_metrics"] is None for h in ("hospital_b", "hospital_c", "hospital_d"))
    # The administrator still sees everything.
    full = client.get(f"/api/federated/rounds/{started['id']}", headers=admin).json()
    assert all(p["local_metrics"] is not None for p in full["participants"])

    metrics = client.get(f"/api/federated/rounds/{started['id']}/metrics", headers=operator).json()
    assert {m["hospital_id"] for m in metrics["local"]} == {"hospital_a"}
    assert {m["hospital_id"] for m in metrics["global_per_hospital"]} == {"hospital_a"}
    assert metrics["global_metrics"] is not None

    mine = client.get("/api/my-hospital", headers=operator).json()["latest_round"]
    assert mine["round_id"] == started["id"] and mine["status"] == "EVALUATED"
    assert mine["update_bytes"] > 0 and mine["num_samples"] > 0
    assert 0.0 <= mine["global_model_on_local_data"]["f1"] <= 1.0
    assert mine["local_model"] is not None


# -------------------------------------------------------- participation
def test_participation_switch_keeps_the_hospital_out_of_new_rounds(client, operator, admin):
    off = client.post("/api/hospitals/hospital_a/participation", json={"participating": False}, headers=operator)
    assert off.status_code == 200 and off.json()["participating"] is False
    assert off.json()["fl_participation"] == "OPTED_OUT"

    started = client.post("/api/federated/rounds/start", json={"modality": "ecg"}, headers=admin).json()
    assert "hospital_a" not in {p["hospital_id"] for p in started["participants"]}
    wait_for_round(client, admin, started["id"])

    on = client.post("/api/hospitals/hospital_a/participation", json={"participating": True}, headers=operator)
    assert on.json()["participating"] is True
    events = _audit(client, admin, "HOSPITAL_PARTICIPATION_CHANGED")
    assert [e["details"]["participating"] for e in events] == [True, False]  # newest first
    assert all(e["actor"] == OPERATOR_A and e["hospital_id"] == "hospital_a" for e in events)


def test_setting_the_same_value_again_is_not_audited(client, operator, admin):
    for _ in range(2):
        client.post("/api/hospitals/hospital_a/participation", json={"participating": False}, headers=operator)
    assert len(_audit(client, admin, "HOSPITAL_PARTICIPATION_CHANGED")) == 1


def test_who_may_switch_participation(client, operator, viewer, coordinator):
    assert client.post("/api/hospitals/hospital_b/participation", json={"participating": False}, headers=operator).status_code == 403
    assert client.post("/api/hospitals/hospital_b/participation", json={"participating": False}, headers=viewer).status_code == 403
    assert client.post("/api/hospitals/hospital_b/participation", json={"participating": False}, headers=coordinator).status_code == 200


def test_round_fails_clearly_when_too_many_hospitals_opted_out(client, admin, coordinator):
    for letter in "abc":
        client.post(f"/api/hospitals/hospital_{letter}/participation", json={"participating": False}, headers=coordinator)
    response = client.post("/api/federated/rounds/start", json={"modality": "ehr"}, headers=admin)
    assert response.status_code == 409 and "switched participation off" in response.json()["detail"]
