"""Roles and scopes: every role is refused outside its permissions and its scope (hospital, jurisdiction)."""

from pathlib import Path

import pytest

from app.services.permissions import PERMISSIONS, ROLE_LABELS, ROLES, SELF_REGISTERED_ONLY
from backend_test_helpers import login

DOCS = Path(__file__).resolve().parents[2] / "docs" / "permissions.md"

ACCOUNTS = {
    "admin": "admin@fl-healthcare.demo",
    "coordinator": "coordinator@fl-healthcare.demo",
    "viewer": "viewer@fl-healthcare.demo",
    "hospital": "hospital_a@fl-healthcare.demo",
    "hospital_manager": "manager_a@fl-healthcare.demo",
    "health_officer": "officer_north@fl-healthcare.demo",
    "researcher": "researcher@fl-healthcare.demo",
}
NORTH = ["R01", "R02", "R03", "R04", "R05", "R06"]
SOUTH = ["R07", "R08", "R09", "R10", "R11", "R12"]

# One request per permission; POSTs carry a valid body so only the permission check can refuse them.
REQUESTS = {
    "dashboard_overview": ("get", "/api/analytics/overview", None),
    "surveillance_read": ("get", "/api/analytics/options", None),
    "explainability_read": ("get", "/api/analytics/privacy", None),
    "hospitals_list": ("get", "/api/hospitals", None),
    "hospital_detail": ("get", "/api/hospitals/hospital_a", None),
    "hospital_participation": ("post", "/api/hospitals/hospital_a/participation", {"participating": True}),
    "hospital_availability": ("post", "/api/hospitals/hospital_b/availability", {"online": True}),
    "my_hospital": ("get", "/api/my-hospital", None),
    "rounds_read": ("get", "/api/federated/rounds", None),
    "rounds_manage": ("post", "/api/federated/rounds/no-such-round/cancel", None),
    "models_read": ("get", "/api/models", None),
    "audit_read": ("get", "/api/audit", None),
    "situation_report": ("get", "/api/officer/forecast-status", None),
    "alerts_read": ("get", "/api/alerts", None),
    "alerts_manage": ("post", "/api/alerts/999999/acknowledge", None),
    "planning_read": ("get", "/api/planning/assumptions", None),
    "capacity_write": ("post", "/api/planning/capacity", {"total_beds": 40, "icu_beds": 4, "occupancy_percent": 70}),
    "assumptions_write": (
        "post",
        "/api/planning/assumptions/dengue",
        {"admission_rate": 0.2, "icu_share": 0.05, "length_of_stay_days": 4},
    ),
    "users_manage": ("get", "/api/users", None),
    "registrations_manage": ("get", "/api/registrations", None),
    "node_token_issue": ("post", "/api/my-hospital/node-token", None),
}


@pytest.fixture
def as_role(client):
    cache = {}

    def headers(role):
        if role not in cache:
            cache[role] = login(client, ACCOUNTS[role])
        return cache[role]

    return headers


def test_every_permission_has_a_request_and_every_role_an_account():
    assert set(REQUESTS) == set(PERMISSIONS)
    assert set(ACCOUNTS) == set(ROLES)


@pytest.mark.parametrize("permission", sorted(PERMISSIONS))
def test_each_role_is_refused_exactly_where_the_table_says(client, as_role, permission):
    method, path, body = REQUESTS[permission]
    allowed = PERMISSIONS[permission][0]
    for role in ROLES:
        response = getattr(client, method)(path, headers=as_role(role), **({"json": body} if body else {}))
        # The "hospital" account here operates built-in hospital A, so self-registered-only access is refused.
        if role in allowed and (permission, role) not in SELF_REGISTERED_ONLY:
            assert response.status_code != 403, (permission, role, response.text)
        else:
            assert response.status_code == 403, (permission, role, response.status_code)


def test_permission_table_in_docs_matches_the_code():
    text = DOCS.read_text(encoding="utf-8")
    header = next(line for line in text.splitlines() if line.startswith("| Permission |"))
    columns = [c.strip() for c in header.strip("|").split("|")]
    assert columns[2:] == [ROLE_LABELS[r] for r in ROLES]
    rows = {}
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip("|").split("|")]
        if line.startswith("| `") and len(cells) == len(columns):
            rows[cells[0].strip("`")] = {role: cell for role, cell in zip(ROLES, cells[2:])}
    assert set(rows) == set(PERMISSIONS)
    for permission, (allowed, _) in PERMISSIONS.items():
        for role in ROLES:
            assert (rows[permission][role] != "-") == (role in allowed), (permission, role)


# ------------------------------------------------------------------ hospital scope
@pytest.mark.parametrize("role", ["hospital", "hospital_manager"])
def test_hospital_roles_open_only_their_own_hospital(client, as_role, role):
    headers = as_role(role)
    assert client.get("/api/hospitals/hospital_a", headers=headers).status_code == 200
    assert client.get("/api/hospitals/hospital_a/metrics", headers=headers).status_code == 200
    assert client.get("/api/hospitals/hospital_b", headers=headers).status_code == 403
    assert client.get("/api/hospitals/hospital_b/metrics", headers=headers).status_code == 403
    assert client.get("/api/my-hospital", headers=headers).json()["hospital"]["id"] == "hospital_a"


def test_hospital_manager_cannot_change_participation_even_for_its_own_hospital(client, as_role):
    response = client.post(
        "/api/hospitals/hospital_a/participation", headers=as_role("hospital_manager"), json={"participating": False}
    )
    assert response.status_code == 403


# ------------------------------------------------------------------ jurisdiction scope
def test_health_officers_see_only_their_jurisdiction(client):
    north = login(client, "officer_north@fl-healthcare.demo")
    south = login(client, "officer_south@fl-healthcare.demo")
    for headers, regions in ((north, NORTH), (south, SOUTH)):
        options = client.get("/api/analytics/options", headers=headers).json()
        assert [r["region_id"] for r in options["regions"]] == regions
        hotspots = client.get("/api/analytics/hotspots", params={"disease": "dengue"}, headers=headers).json()
        assert sorted(r["region_id"] for r in hotspots["regions"]) == regions
        assert sorted(f["properties"]["region_id"] for f in hotspots["geojson"]["features"]) == regions
        assert sum(hotspots["summary"].values()) == len(regions)
        assert all(set(r["adjacent_flagged_regions"]) <= set(regions) for r in hotspots["regions"])


def test_health_officer_status_matches_the_full_view(client, viewer):
    """Scoping filters what is shown; it does not change how a region is assessed."""
    north = login(client, "officer_north@fl-healthcare.demo")
    params = {"disease": "dengue"}
    full = {r["region_id"]: r["status"] for r in client.get("/api/analytics/hotspots", params=params, headers=viewer).json()["regions"]}
    scoped = {r["region_id"]: r["status"] for r in client.get("/api/analytics/hotspots", params=params, headers=north).json()["regions"]}
    assert scoped == {region: full[region] for region in NORTH}


def test_health_officer_is_refused_a_forecast_outside_the_jurisdiction(client):
    north = login(client, "officer_north@fl-healthcare.demo")
    outside = client.get("/api/analytics/forecast", params={"region_id": "R07", "disease": "dengue", "horizon": 2}, headers=north)
    assert outside.status_code == 403
    assert "outside your jurisdiction" in outside.json()["detail"]
    default = client.get("/api/analytics/forecast", params={"disease": "dengue", "horizon": 2}, headers=north)
    assert default.status_code == 200 and default.json()["region_id"] in NORTH


def test_unscoped_roles_see_every_region(client, as_role):
    for role in ("viewer", "researcher", "hospital_manager"):
        options = client.get("/api/analytics/options", headers=as_role(role)).json()
        assert len(options["regions"]) == 12


# ------------------------------------------------------------------ assigning roles
def _new_user(client, email):
    response = client.post("/api/auth/register", json={"email": email, "password": "long-enough-pw"})
    assert response.status_code == 200, response.text
    return response.json()["user"]["id"]


def test_admin_assigns_scoped_roles_with_validation_and_audit(client, admin):
    user_id = _new_user(client, "new.officer@example.org")
    url = f"/api/users/{user_id}/role"
    assert client.post(url, headers=admin, json={"role": "health_officer"}).status_code == 422
    assert client.post(url, headers=admin, json={"role": "health_officer", "jurisdiction": ["R99"]}).status_code == 422
    assert client.post(url, headers=admin, json={"role": "hospital_manager"}).status_code == 422

    changed = client.post(url, headers=admin, json={"role": "health_officer", "jurisdiction": ["R03", "R01"]})
    assert changed.status_code == 200 and changed.json()["jurisdiction"] == ["R01", "R03"]
    officer = login_registered(client, "new.officer@example.org")
    options = client.get("/api/analytics/options", headers=officer).json()
    assert [r["region_id"] for r in options["regions"]] == ["R01", "R03"]

    researcher = client.post(url, headers=admin, json={"role": "researcher", "jurisdiction": ["R01"]})
    assert researcher.json()["jurisdiction"] is None  # only health officers keep a jurisdiction

    entries = client.get("/api/audit", params={"action": "USER_ROLE_CHANGED"}, headers=admin).json()["items"]
    details = [e["details"] for e in entries if e["details"].get("user") == "new.officer@example.org"]
    assert any(d.get("jurisdiction_to") == ["R01", "R03"] for d in details)


def login_registered(client, email):
    response = client.post("/api/auth/demo-login", json={"email": email, "password": "long-enough-pw"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_only_admins_assign_roles(client, as_role):
    for role in ROLES:
        if role == "admin":
            continue
        response = client.post("/api/users/demo-viewer/role", headers=as_role(role), json={"role": "researcher"})
        assert response.status_code == 403, role


# ------------------------------------------------------------------ migration
def test_existing_users_table_gains_the_jurisdiction_column():
    from app.database import Database

    db = Database("sqlite:///:memory:")
    db.execute(
        "CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, display_name TEXT, role TEXT NOT NULL, "
        "hospital_id TEXT, created_at TEXT NOT NULL, last_login_at TEXT)"
    )
    db.create_schema()
    assert "jurisdiction" in db.table_columns()["users"]
