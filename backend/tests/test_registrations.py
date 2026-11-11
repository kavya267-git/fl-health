"""Hospital onboarding: registration, approval, sign-in, node tokens, data checks and invitations."""

from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.registration_service import RateLimiter
from app.utils.errors import RateLimited
from backend_test_helpers import login

PASSWORD = "city-hospital-pass"


def form(**overrides):
    body = {
        "hospital_name": "Test City Hospital",
        "region_id": "R03",
        "contact_name": "Asha Rao",
        "contact_email": "ops@testcity.example",
        "password": PASSWORD,
        "password_confirm": PASSWORD,
        "modalities": ["ecg", "ehr"],
        "approx_record_counts": {"ecg": 500, "ehr": 900},
        "confirm_no_patient_data": True,
    }
    body.update(overrides)
    return body


@pytest.fixture
def external_client(settings):
    with TestClient(create_app(settings.model_copy(update={"hospital_nodes": "external"}))) as client:
        yield client


def _sign_in(client, email=form()["contact_email"], password=PASSWORD):
    return client.post("/api/auth/demo-login", json={"email": email, "password": password})


def _register_and_approve(client):
    receipt = client.post("/api/registrations", json=form())
    assert receipt.status_code == 201, receipt.text
    admin = login(client, "admin@fl-healthcare.demo")
    approved = client.post(f"/api/registrations/{receipt.json()['id']}/approve", headers=admin)
    assert approved.status_code == 200, approved.text
    return receipt.json()["id"], approved.json()["hospital_id"], admin


# ------------------------------------------------------------------ registration
def test_registration_is_pending_and_its_account_cannot_sign_in(client):
    receipt = client.post("/api/registrations", json=form())
    assert receipt.status_code == 201
    assert receipt.json()["status"] == "PENDING"
    refused = _sign_in(client)
    assert refused.status_code == 401 and "waiting for an administrator" in refused.json()["detail"]
    # A wrong password does not reveal that the account exists.
    assert "Incorrect" in _sign_in(client, password="wrong-password-1").json()["detail"]


def test_password_is_stored_as_scrypt_hash_only(client):
    client.post("/api/registrations", json=form())
    ctx = client.app.state.ctx
    row = ctx.db.fetch_one(
        "SELECT c.password_hash FROM local_credentials c JOIN users u ON u.id = c.user_id WHERE u.email = :e",
        {"e": form()["contact_email"]},
    )
    assert row["password_hash"].startswith("scrypt$") and PASSWORD not in row["password_hash"]
    stored = ctx.db.fetch_one("SELECT * FROM hospital_registrations")
    assert PASSWORD not in str(stored)


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"hospital_name": "x"}, "hospital name"),
        ({"region_id": "R99"}, "region"),
        ({"contact_email": "not-an-email"}, "email"),
        ({"password": "short", "password_confirm": "short"}, "at least"),
        ({"password_confirm": "something-else"}, "do not match"),
        ({"modalities": []}, "at least one"),
        ({"modalities": ["ehr", "mri"], "approx_record_counts": {"ehr": 5}}, "Modalities"),
        ({"approx_record_counts": {"ecg": 500}}, "EHR"),
        ({"approx_record_counts": {"ecg": 0, "ehr": 900}}, "between 1"),
        ({"approx_record_counts": {"ecg": 500, "ehr": 900, "xray": 3}}, "no other"),
        ({"confirm_no_patient_data": False}, "Tick the box"),
    ],
)
def test_registration_validation(client, overrides, message):
    response = client.post("/api/registrations", json=form(**overrides))
    assert response.status_code == 422, response.text
    assert message.lower() in response.json()["detail"].lower()


def test_unknown_fields_such_as_uploads_are_refused(client):
    assert client.post("/api/registrations", json=form(patient_file="rows.csv")).status_code == 422


def test_duplicate_email_and_hospital_name_are_refused(client):
    assert client.post("/api/registrations", json=form()).status_code == 201
    assert client.post("/api/registrations", json=form(hospital_name="Other")).status_code == 409
    assert client.post("/api/registrations", json=form(contact_email="b@x.example")).status_code == 409


def test_rate_limit_per_address(client):
    limiter = client.app.state.ctx.registrations.limiter
    limiter.per_key = 2
    for i in range(2):
        assert client.post("/api/registrations", json=form(hospital_name=f"H{i} Hospital", contact_email=f"h{i}@x.example")).status_code == 201
    limited = client.post("/api/registrations", json=form(hospital_name="H9 Hospital", contact_email="h9@x.example"))
    assert limited.status_code == 429


def test_rate_limiter_window_and_global_cap():
    now = [0.0]
    limiter = RateLimiter(per_key=2, global_limit=3, window_seconds=10, clock=lambda: now[0])
    limiter.check("a")
    limiter.check("a")
    with pytest.raises(RateLimited):
        limiter.check("a")
    limiter.check("b")
    with pytest.raises(RateLimited):  # global cap reached
        limiter.check("c")
    now[0] = 11
    limiter.check("a")


def test_registrations_are_admin_only_and_not_public(client):
    client.post("/api/registrations", json=form())
    assert client.get("/api/registrations").status_code == 401
    for account in ("coordinator@fl-healthcare.demo", "viewer@fl-healthcare.demo", "hospital_a@fl-healthcare.demo"):
        headers = login(client, account)
        assert client.get("/api/registrations", headers=headers).status_code == 403
        assert client.post("/api/registrations/x/approve", headers=headers).status_code == 403
    admin = login(client, "admin@fl-healthcare.demo")
    assert client.get("/api/registrations/pending-count", headers=admin).json() == {"pending": 1}
    # The public region list carries ids and names only.
    regions = client.get("/api/registrations/regions").json()
    assert regions and set(regions[0]) == {"region_id", "name"}


# ------------------------------------------------------------------ review
def test_approve_creates_hospital_and_enables_operator(client):
    registration_id, hospital_id, admin = _register_and_approve(client)
    assert hospital_id == "hospital_test_city_hospital"
    signed_in = _sign_in(client)
    assert signed_in.status_code == 200
    user = signed_in.json()["user"]
    assert user["role"] == "hospital" and user["hospital_id"] == hospital_id
    hospital = client.app.state.ctx.hospitals.get_raw(hospital_id)
    assert hospital["kind"] == "registered" and hospital["region_id"] == "R03"
    assert hospital["declared_modalities"] == ["ehr", "ecg"] and hospital["modalities"] == []
    assert client.post(f"/api/registrations/{registration_id}/approve", headers=admin).status_code == 409


def test_slug_never_reuses_an_existing_id(client):
    admin = login(client, "admin@fl-healthcare.demo")

    def approve(name, email):
        receipt = client.post("/api/registrations", json=form(hospital_name=name, contact_email=email))
        assert receipt.status_code == 201, receipt.text
        return client.post(f"/api/registrations/{receipt.json()['id']}/approve", headers=admin).json()["hospital_id"]

    assert approve("Hospital A", "a@x.example") == "hospital_hospital_a"
    assert approve("Hospital A!", "b@x.example") == "hospital_hospital_a_2"
    # A name whose slug is a built-in hospital's id ("a" -> hospital_a) never takes that id.
    assert client.app.state.ctx.registrations._unique_hospital_id("A") == "hospital_a_2"


def test_reject_keeps_account_disabled_and_stores_reason(client):
    receipt = client.post("/api/registrations", json=form()).json()
    admin = login(client, "admin@fl-healthcare.demo")
    assert client.post(f"/api/registrations/{receipt['id']}/reject", headers=admin, json={"reason": ""}).status_code == 422
    rejected = client.post(f"/api/registrations/{receipt['id']}/reject", headers=admin, json={"reason": "Not a hospital"}).json()
    assert rejected["status"] == "REJECTED" and rejected["reason"] == "Not a hospital"
    response = _sign_in(client)
    assert response.status_code == 401 and "not active" in response.json()["detail"]


def test_every_step_is_audited(client):
    registration_id, hospital_id, admin = _register_and_approve(client)
    operator = {"Authorization": f"Bearer {_sign_in(client).json()['access_token']}"}
    client.post("/api/my-hospital/node-token", headers=operator)
    client.post(f"/api/registrations/{registration_id}/revoke", headers=admin, json={"reason": "Left the pilot"})
    actions = [a["action"] for a in client.get("/api/audit", params={"limit": 200}, headers=admin).json()["items"]]
    for action in (
        "HOSPITAL_REGISTRATION_SUBMITTED",
        "HOSPITAL_REGISTRATION_APPROVED",
        "NODE_TOKEN_ISSUED",
        "HOSPITAL_REGISTRATION_REVOKED",
    ):
        assert action in actions
    assert client.get("/api/audit/verify", headers=admin).json()["valid"] is True


# ------------------------------------------------------------------ node token
def test_token_shown_once_stored_hashed_and_regeneration_revokes_old(external_client):
    client = external_client
    _, hospital_id, _ = _register_and_approve(client)
    operator = {"Authorization": f"Bearer {_sign_in(client).json()['access_token']}"}
    first = client.post("/api/my-hospital/node-token", headers=operator).json()["token"]
    stored = client.app.state.ctx.db.fetch_one("SELECT * FROM node_tokens WHERE hospital_id = :h", {"h": hospital_id})
    assert stored["token_hash"] == hashlib.sha256(first.encode()).hexdigest() and first not in str(stored)
    # Never returned again.
    page = client.get("/api/my-hospital", headers=operator).json()
    assert first not in str(page) and page["connection"]["token"]["created_at"]
    beat = {"hospital_id": hospital_id, "data_summary": {}}
    assert client.post("/api/federated/node/heartbeat", json=beat, headers={"X-Hospital-Token": first}).status_code == 200
    second = client.post("/api/my-hospital/node-token", headers=operator).json()["token"]
    assert client.post("/api/federated/node/heartbeat", json=beat, headers={"X-Hospital-Token": first}).status_code == 403
    assert client.post("/api/federated/node/heartbeat", json=beat, headers={"X-Hospital-Token": second}).status_code == 200


def test_hmac_token_does_not_work_for_registered_hospitals(external_client):
    client = external_client
    _, hospital_id, _ = _register_and_approve(client)
    derived = client.app.state.ctx.hospitals.node_token(hospital_id)
    response = client.post(
        "/api/federated/node/heartbeat", json={"hospital_id": hospital_id}, headers={"X-Hospital-Token": derived}
    )
    assert response.status_code == 403


def test_builtin_hospitals_keep_their_hmac_tokens(external_client):
    client = external_client
    token = client.app.state.ctx.hospitals.node_token("hospital_a")
    response = client.post("/api/federated/node/heartbeat", json={"hospital_id": "hospital_a"}, headers={"X-Hospital-Token": token})
    assert response.status_code == 200
    operator = login(client, "hospital_a@fl-healthcare.demo")
    assert client.post("/api/my-hospital/node-token", headers=operator).status_code == 409


def test_revoke_disables_account_and_token_at_once(external_client):
    client = external_client
    registration_id, hospital_id, admin = _register_and_approve(client)
    session = _sign_in(client).json()["access_token"]
    operator = {"Authorization": f"Bearer {session}"}
    token = client.post("/api/my-hospital/node-token", headers=operator).json()["token"]
    client.post(f"/api/registrations/{registration_id}/revoke", headers=admin, json={"reason": "Pilot ended"})
    assert client.post("/api/federated/node/heartbeat", json={"hospital_id": hospital_id}, headers={"X-Hospital-Token": token}).status_code == 403
    assert client.get("/api/my-hospital", headers=operator).status_code == 401  # the existing session ends too
    assert _sign_in(client).status_code == 401


# ------------------------------------------------------------------ data check and invitations
def _connect(client, hospital_id, token, summary, check):
    headers = {"X-Hospital-Token": token}
    assert client.post("/api/federated/node/data-check", json={"hospital_id": hospital_id, "modalities": check}, headers=headers).status_code == 200
    beat = {"hospital_id": hospital_id, "ml_backend": "numpy-reference", "data_summary": summary}
    assert client.post("/api/federated/node/heartbeat", json=beat, headers=headers).status_code == 200


def test_node_is_invited_only_for_declared_modalities_that_passed(external_client):
    client = external_client
    _, hospital_id, admin = _register_and_approve(client)  # declared EHR and ECG
    operator = {"Authorization": f"Bearer {_sign_in(client).json()['access_token']}"}
    token = client.post("/api/my-hospital/node-token", headers=operator).json()["token"]
    profile = client.get("/api/federated/node/profile", params={"hospital_id": hospital_id}, headers={"X-Hospital-Token": token}).json()
    assert profile["declared_modalities"] == ["ehr", "ecg"] and profile["registered"] is True
    entry = {"source": "simulated", "simulated": True, "train_samples": 90, "val_samples": 30}
    summary = {"ehr": entry, "ecg": entry, "xray": entry}  # X-ray present locally but not declared
    check = {
        "ehr": {"passed": False, "train_records": 90, "val_records": 30, "problems": ["train: 'age' outside 0-120"]},
        "ecg": {"passed": True, "train_records": 90, "val_records": 30, "label_counts": {"N": 60, "S": 30}},
        "xray": {"passed": True, "train_records": 90, "val_records": 30},
    }
    _connect(client, hospital_id, token, summary, check)
    hospital = client.app.state.ctx.hospitals.get_raw(hospital_id)
    assert hospital["modalities"] == ["ecg"]
    assert "xray" not in hospital["data_check"]  # undeclared modality ignored
    page = client.get("/api/my-hospital", headers=operator).json()["connection"]
    assert page["step"] == "INVITED" and page["invited_modalities"] == ["ecg"]
    assert page["data_check"]["ehr"]["problems"] == ["train: 'age' outside 0-120"]

    for h in ("hospital_a", "hospital_b"):
        client.post("/api/federated/node/heartbeat", json={"hospital_id": h, "data_summary": summary},
                    headers={"X-Hospital-Token": client.app.state.ctx.hospitals.node_token(h)})
    ecg = client.post("/api/federated/rounds/start", json={"modality": "ecg"}, headers=admin).json()
    assert hospital_id in {p["hospital_id"] for p in ecg["participants"]}
    client.post(f"/api/federated/rounds/{ecg['id']}/cancel", headers=admin)
    ehr = client.post("/api/federated/rounds/start", json={"modality": "ehr"}, headers=admin).json()
    assert hospital_id not in {p["hospital_id"] for p in ehr["participants"]}


def test_data_check_report_keeps_counts_only(external_client):
    client = external_client
    _, hospital_id, _ = _register_and_approve(client)
    operator = {"Authorization": f"Bearer {_sign_in(client).json()['access_token']}"}
    token = client.post("/api/my-hospital/node-token", headers=operator).json()["token"]
    report = {"ecg": {"passed": True, "train_records": 5, "val_records": 2, "rows": [[0.1, 0.2]], "patient": "x"}}
    stored = client.post("/api/federated/node/data-check", json={"hospital_id": hospital_id, "modalities": report},
                         headers={"X-Hospital-Token": token}).json()["data_check"]["ecg"]
    assert set(stored) == {"passed", "train_records", "val_records", "label_counts", "problems", "checked_at"}


def test_privacy_schema_check_still_passes(client):
    admin = login(client, "admin@fl-healthcare.demo")
    checks = {c["id"]: c for c in client.get("/api/analytics/privacy", headers=admin).json()["checks"]}
    assert checks["central_schema"]["status"] == "PASS"
