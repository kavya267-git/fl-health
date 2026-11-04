"""Who may do what: one table, used by the routers and documented in docs/permissions.md.

Three scope rules sit on top of the table:

* hospital operators and hospital managers see one hospital's detail pages: their own (``hospital_id``);
* health officers see surveillance and forecasts only for the regions in their jurisdiction;
* everything else in a row applies to all data the endpoint covers.

A test (backend/tests/test_permissions.py) checks that docs/permissions.md matches this table.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from app.utils.errors import PermissionDenied

ROLES = ("admin", "coordinator", "viewer", "hospital", "hospital_manager", "health_officer", "researcher")

ROLE_LABELS = {
    "admin": "Administrator",
    "coordinator": "FL coordinator",
    "viewer": "Viewer",
    "hospital": "Hospital operator",
    "hospital_manager": "Hospital manager",
    "health_officer": "Health officer",
    "researcher": "Researcher",
}

#: Roles that act for one hospital; such a user must have users.hospital_id set.
HOSPITAL_ROLES = ("hospital", "hospital_manager")
#: Roles whose surveillance access is limited to users.jurisdiction (a list of region ids).
JURISDICTION_ROLES = ("health_officer",)

_READ_FEDERATION = ("admin", "coordinator", "viewer", "hospital", "hospital_manager", "researcher")

#: permission -> (roles allowed, what it covers)
PERMISSIONS: Dict[str, tuple] = {
    "dashboard_overview": (_READ_FEDERATION, "GET /api/analytics/overview"),
    "surveillance_read": (ROLES, "GET /api/analytics/options, /hotspots, /forecast"),
    "explainability_read": (_READ_FEDERATION, "GET /api/analytics/explainability, /privacy"),
    "hospitals_list": (_READ_FEDERATION, "GET /api/hospitals"),
    "hospital_detail": (
        ("admin", "coordinator", "viewer", "hospital", "hospital_manager"),
        "GET /api/hospitals/{id}, /{id}/metrics",
    ),
    "hospital_participation": (("admin", "coordinator", "hospital"), "POST /api/hospitals/{id}/participation"),
    "hospital_availability": (("admin", "coordinator"), "POST /api/hospitals/{id}/availability"),
    "my_hospital": (HOSPITAL_ROLES, "GET /api/my-hospital"),
    "rounds_read": (_READ_FEDERATION, "GET /api/federated/rounds, /rounds/{id}, /rounds/{id}/metrics"),
    "rounds_manage": (("admin", "coordinator"), "POST /api/federated/rounds/start, /aggregate, /finalize, /cancel"),
    "models_read": (_READ_FEDERATION, "GET /api/models, /models/{id}, /models/{id}/metrics"),
    "audit_read": (("admin", "coordinator"), "GET /api/audit, /api/audit/verify"),
    "situation_report": (
        ("admin", "coordinator", "health_officer"),
        "GET /api/officer/situation, /situation.csv, /situation.pdf, /forecast-status",
    ),
    "alerts_read": (("admin", "coordinator", "health_officer"), "GET /api/alerts"),
    "alerts_manage": (("admin", "health_officer"), "POST /api/alerts/{id}/acknowledge, /{id}/outcome"),
    "users_manage": (("admin",), "GET /api/users, POST /api/users/{id}/role"),
}

#: Roles that may read the audit log (the /api/audit endpoints and the dashboard's recent activity).
AUDIT_READER_ROLES = PERMISSIONS["audit_read"][0]


def allowed_roles(permission: str) -> tuple:
    return PERMISSIONS[permission][0]


def require_permission(user: Dict[str, Any], permission: str) -> None:
    roles = allowed_roles(permission)
    if user.get("role") not in roles:
        label = ROLE_LABELS.get(user.get("role"), user.get("role"))
        raise PermissionDenied(f"Your role ({label}) does not have access to this.")


def ensure_hospital_scope(user: Dict[str, Any], hospital_id: str) -> None:
    """Hospital operators and managers may open only their own hospital's details."""
    if user.get("role") in HOSPITAL_ROLES and user.get("hospital_id") != hospital_id:
        raise PermissionDenied("You can only open your own hospital's details.")


def jurisdiction_of(user: Dict[str, Any]) -> Optional[List[str]]:
    """The regions this user may see, or None when the role is not limited to a jurisdiction."""
    if user.get("role") not in JURISDICTION_ROLES:
        return None
    return list(user.get("jurisdiction") or [])


def ensure_region_scope(user: Dict[str, Any], region_ids: Iterable[str]) -> None:
    allowed = jurisdiction_of(user)
    if allowed is None:
        return
    outside = sorted(set(region_ids) - set(allowed))
    if outside:
        raise PermissionDenied(f"Region {', '.join(outside)} is outside your jurisdiction.")
