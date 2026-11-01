"""Sign-up, sign-in for created accounts, and role management by the administrator."""

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.context import bootstrap, build_context
from app.utils.errors import PermissionDenied
from backend_test_helpers import DEMO_PASSWORD

NEW = {"email": "Priya@Example.org", "password": "correct horse 42", "display_name": "  Priya   N  "}


def register(client, **overrides):
    return client.post("/api/auth/register", json={**NEW, **overrides})


def bearer(response) -> dict:
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_config_tells_the_sign_in_page_that_sign_up_is_available(client):
    config = client.get("/api/system/config").json()
    assert config["signup_enabled"] is True


def test_sign_up_creates_a_viewer_and_signs_it_in(client):
    response = register(client)
    assert response.status_code == 200, response.text
    user = response.json()["user"]
    assert user["email"] == "priya@example.org" and user["display_name"] == "Priya N"
    assert user["role"] == "viewer"

    headers = bearer(response)
    assert client.get("/api/auth/me", headers=headers).json()["role"] == "viewer"
    assert client.get("/api/hospitals", headers=headers).status_code == 200  # can read dashboards
    # ...but cannot change anything or see restricted pages
    assert client.post("/api/federated/rounds/start", json={"modality": "ehr"}, headers=headers).status_code == 403
    assert client.get("/api/audit", headers=headers).status_code == 403
    assert client.get("/api/users", headers=headers).status_code == 403


def test_a_role_cannot_be_chosen_at_sign_up(client):
    response = register(client, role="admin", is_admin=True)
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "viewer"


def test_created_account_signs_in_with_its_own_password_only(client):
    register(client)
    good = client.post("/api/auth/demo-login", json={"email": "priya@example.org", "password": NEW["password"]})
    assert good.status_code == 200 and good.json()["user"]["role"] == "viewer"
    for password in ("wrong password", DEMO_PASSWORD):
        bad = client.post("/api/auth/demo-login", json={"email": "priya@example.org", "password": password})
        assert bad.status_code == 401 and bad.json()["detail"] == "Incorrect email or password."
    unknown = client.post("/api/auth/demo-login", json={"email": "nobody@example.org", "password": "whatever-1"})
    assert unknown.status_code == 401 and unknown.json()["detail"] == "Incorrect email or password."


def test_password_is_stored_hashed(client):
    register(client)
    db = client.app.state.ctx.db
    row = db.fetch_one("SELECT password_hash FROM local_credentials")
    assert row["password_hash"].startswith("scrypt$") and NEW["password"] not in row["password_hash"]
    assert "password" not in " ".join(db.table_columns()["users"])


@pytest.mark.parametrize(
    "overrides, status, message",
    [
        ({"email": "not-an-email"}, 422, "valid email"),
        ({"password": "short"}, 422, "at least 8 characters"),
        ({"email": "admin@fl-healthcare.demo"}, 409, "already exists"),
    ],
)
def test_sign_up_is_rejected_with_a_clear_reason(client, overrides, status, message):
    response = register(client, **overrides)
    assert response.status_code == status and message in response.json()["detail"]


def test_an_email_can_only_be_registered_once(client):
    assert register(client).status_code == 200
    again = register(client, email="PRIYA@example.org", password="another password")
    assert again.status_code == 409
    assert len(client.app.state.ctx.db.fetch_all("SELECT user_id FROM local_credentials")) == 1


def test_administrator_changes_roles_and_others_cannot(client, admin, coordinator):
    created = register(client)
    user_id = created.json()["user"]["id"]
    headers = bearer(created)

    users = client.get("/api/users", headers=admin).json()
    by_email = {user["email"]: user for user in users}
    assert by_email["priya@example.org"]["role"] == "viewer" and not by_email["priya@example.org"]["role_locked"]
    assert by_email["admin@fl-healthcare.demo"]["built_in"] and by_email["admin@fl-healthcare.demo"]["role_locked"]

    # A coordinator is not an administrator.
    assert client.get("/api/users", headers=coordinator).status_code == 403
    denied = client.post(f"/api/users/{user_id}/role", json={"role": "admin"}, headers=coordinator)
    assert denied.status_code == 403
    # Nobody promotes themselves.
    assert client.post(f"/api/users/{user_id}/role", json={"role": "admin"}, headers=headers).status_code == 403

    promoted = client.post(f"/api/users/{user_id}/role", json={"role": "coordinator"}, headers=admin)
    assert promoted.status_code == 200 and promoted.json()["role"] == "coordinator"
    # The existing session picks up the new role: roles are read from the database, not the token.
    assert client.get("/api/auth/me", headers=headers).json()["role"] == "coordinator"
    assert client.get("/api/audit", headers=headers).status_code == 200
    assert client.get("/api/users", headers=headers).status_code == 403

    assert client.post(f"/api/users/{user_id}/role", json={"role": "owner"}, headers=admin).status_code == 422
    assert client.post("/api/users/missing/role", json={"role": "viewer"}, headers=admin).status_code == 404


def test_administrator_cannot_change_own_role_or_a_built_in_account(client, admin):
    own = client.post("/api/users/demo-admin/role", json={"role": "viewer"}, headers=admin)
    assert own.status_code == 409 and "your own role" in own.json()["detail"]
    built_in = client.post("/api/users/demo-viewer/role", json={"role": "admin"}, headers=admin)
    assert built_in.status_code == 409 and "Built-in demo accounts" in built_in.json()["detail"]
    assert client.get("/api/auth/me", headers=admin).json()["role"] == "admin"


def test_sign_up_and_role_changes_are_audited(client, admin):
    user_id = register(client).json()["user"]["id"]
    client.post(f"/api/users/{user_id}/role", json={"role": "coordinator"}, headers=admin)
    items = client.get("/api/audit", params={"limit": 200}, headers=admin).json()["items"]
    registered = next(item for item in items if item["action"] == "USER_REGISTERED")
    assert registered["actor"] == "priya@example.org" and registered["details"]["role"] == "viewer"
    changed = next(item for item in items if item["action"] == "USER_ROLE_CHANGED")
    assert changed["actor"] == "admin@fl-healthcare.demo"
    assert changed["details"] == {"user": "priya@example.org", "from": "viewer", "to": "coordinator"}
    assert NEW["password"] not in str(items)
    assert client.get("/api/audit/verify", headers=admin).json()["valid"] is True


def test_sign_up_can_be_switched_off(settings):
    closed = settings.model_copy(update={"allow_signup": False})
    with TestClient(create_app(closed)) as client:
        assert client.get("/api/system/config").json()["signup_enabled"] is False
        response = register(client)
        assert response.status_code == 403 and "switched off" in response.json()["detail"]


def test_with_supabase_accounts_are_not_created_by_this_api(tmp_path):
    settings = Settings(
        demo_mode=True,
        auth_provider="supabase",
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="service-role-key",
        admin_emails=["lead@hospital.example"],
        node_token_secret="node-secret",
        simulation_scale=0.2,
        database_url=f"sqlite:///{(tmp_path / 'supabase.db').as_posix()}",
        model_storage_path=tmp_path / "models",
        hospital_data_root=tmp_path / "hospitals",
    )
    ctx = build_context(settings)
    try:
        bootstrap(ctx)
        with pytest.raises(PermissionDenied, match="Supabase Auth"):
            ctx.auth.register("someone@hospital.example", "long enough password")
        # An administrator named in ADMIN_EMAILS cannot be demoted from the dashboard.
        ctx.db.insert(
            "users",
            {
                "id": "u-lead",
                "email": "lead@hospital.example",
                "display_name": "Lead",
                "role": "admin",
                "hospital_id": None,
                "created_at": "2026-01-01T00:00:00+00:00",
            },
        )
        lead = next(user for user in ctx.auth.list_users() if user["id"] == "u-lead")
        assert lead["role_locked"] and "ADMIN_EMAILS" in lead["role_locked_reason"]
    finally:
        ctx.close()
