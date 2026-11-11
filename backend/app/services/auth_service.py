"""Authentication and role lookup.

Two identity providers sit behind one interface:

* ``SupabaseAuthProvider`` - verifies a Supabase Auth access token by asking
  Supabase for the user it belongs to. Used whenever Supabase is configured.
* ``DemoAuthProvider`` - issues and verifies locally signed tokens for three
  built-in demo accounts and for accounts created through the sign-up form
  (password hashes in ``local_credentials``). Available only when
  DEMO_MODE=true and Supabase is not configured, so a demonstration can run
  without external services.

Roles live in the ``users`` table, not in the token:

    admin        everything, including changing other users' roles
    coordinator  start / aggregate rounds, change hospital availability, read audit log
    viewer       read-only access to dashboards

Nobody can sign up as an administrator. A new account - from the sign-up form
or first seen through Supabase - is always a viewer. The administrator is a
separate account: the built-in demo administrator, or the emails listed in
ADMIN_EMAILS when Supabase is used. Only an administrator can change a role.
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import jwt
import requests

from app.database import Database, DatabaseError
from app.services.audit_service import AuditService
from app.services.permissions import (  # noqa: E402 - re-exported for existing imports
    HOSPITAL_ROLES,
    JURISDICTION_ROLES,
    ROLE_LABELS,
    ROLES,
)
from app.utils.errors import (
    AuthenticationFailed,
    ConflictError,
    NotFoundError,
    PermissionDenied,
    UnavailableError,
    ValidationFailed,
)
from app.utils.hashing import constant_time_equal
from app.utils.passwords import DUMMY_HASH, hash_password, verify_password
from app.utils.time import utc_now_iso

#: Role of every newly created account. Never anything else.
DEFAULT_ROLE = "viewer"
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 256
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DEMO_ISSUER = "fl-healthcare-demo"
DEMO_TOKEN_TTL_SECONDS = 12 * 3600

DEMO_ACCOUNTS = [
    {"id": "demo-admin", "email": "admin@fl-healthcare.demo", "display_name": "Demo Administrator", "role": "admin"},
    {
        "id": "demo-coordinator",
        "email": "coordinator@fl-healthcare.demo",
        "display_name": "Demo FL Coordinator",
        "role": "coordinator",
    },
    {"id": "demo-viewer", "email": "viewer@fl-healthcare.demo", "display_name": "Demo Analyst", "role": "viewer"},
] + [
    # One operator per simulated hospital: signs in on that hospital's own laptop.
    {
        "id": f"demo-hospital-{letter}",
        "email": f"hospital_{letter}@fl-healthcare.demo",
        "display_name": f"Hospital {letter.upper()} operator",
        "role": "hospital",
        "hospital_id": f"hospital_{letter}",
    }
    for letter in "abcd"
] + [
    # Two health officers with different jurisdictions (simulated region ids R01-R12), a researcher and a
    # hospital manager. With REGIONS_GEOJSON_PATH set the region ids differ, so assign real jurisdictions
    # to real accounts under Settings instead.
    {
        "id": "demo-officer-north",
        "email": "officer_north@fl-healthcare.demo",
        "display_name": "Health officer, regions R01-R06",
        "role": "health_officer",
        "jurisdiction": ["R01", "R02", "R03", "R04", "R05", "R06"],
    },
    {
        "id": "demo-officer-south",
        "email": "officer_south@fl-healthcare.demo",
        "display_name": "Health officer, regions R07-R12",
        "role": "health_officer",
        "jurisdiction": ["R07", "R08", "R09", "R10", "R11", "R12"],
    },
    {"id": "demo-researcher", "email": "researcher@fl-healthcare.demo", "display_name": "Demo Researcher", "role": "researcher"},
    {
        "id": "demo-manager-a",
        "email": "manager_a@fl-healthcare.demo",
        "display_name": "Hospital A manager",
        "role": "hospital_manager",
        "hospital_id": "hospital_a",
    },
]
_BUILT_IN_BY_EMAIL = {account["email"]: account for account in DEMO_ACCOUNTS}
_BUILT_IN_IDS = {account["id"] for account in DEMO_ACCOUNTS}


@dataclass
class Identity:
    subject: str
    email: str


class SupabaseAuthProvider:
    name = "supabase"

    def __init__(self, supabase_url: str, api_key: str, cache_seconds: int = 60):
        self._endpoint = f"{supabase_url.rstrip('/')}/auth/v1/user"
        self._api_key = api_key
        self._cache_seconds = cache_seconds
        self._cache: Dict[str, tuple] = {}
        self._lock = threading.Lock()

    def verify(self, token: str) -> Identity:
        key = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(key)
            if cached and cached[0] > now:
                return cached[1]
        try:
            response = requests.get(
                self._endpoint,
                headers={"apikey": self._api_key, "Authorization": f"Bearer {token}"},
                timeout=10,
            )
        except requests.RequestException as exc:
            raise UnavailableError("The authentication service could not be reached.") from exc
        if response.status_code in (401, 403):
            raise AuthenticationFailed("Your session is invalid or has expired. Sign in again.")
        if response.status_code >= 400:
            raise UnavailableError(f"The authentication service returned an error ({response.status_code}).")
        body = response.json()
        if not body.get("id") or not body.get("email"):
            raise AuthenticationFailed("The authentication service did not return a user for this session.")
        identity = Identity(subject=str(body["id"]), email=str(body["email"]).lower())
        with self._lock:
            if len(self._cache) > 1000:
                self._cache.clear()
            self._cache[key] = (now + self._cache_seconds, identity)
        return identity


class DemoAuthProvider:
    name = "demo"

    def __init__(self, secret: str, password: str):
        self._secret = secret
        self._password = password

    def built_in_password_matches(self, password: str) -> bool:
        return constant_time_equal(self._password, password)

    def issue(self, subject: str, email: str) -> Dict[str, Any]:
        now = int(time.time())
        token = jwt.encode(
            {
                "sub": subject,
                "email": email,
                "iss": DEMO_ISSUER,
                "iat": now,
                "exp": now + DEMO_TOKEN_TTL_SECONDS,
            },
            self._secret,
            algorithm="HS256",
        )
        return {"access_token": token, "token_type": "bearer", "expires_in": DEMO_TOKEN_TTL_SECONDS}

    def verify(self, token: str) -> Identity:
        try:
            claims = jwt.decode(token, self._secret, algorithms=["HS256"], issuer=DEMO_ISSUER)
        except jwt.ExpiredSignatureError as exc:
            raise AuthenticationFailed("Your session has expired. Sign in again.") from exc
        except jwt.InvalidTokenError as exc:
            raise AuthenticationFailed("Your session is invalid. Sign in again.") from exc
        return Identity(subject=str(claims["sub"]), email=str(claims["email"]).lower())


class AuthService:
    def __init__(self, db: Database, audit: AuditService, settings):
        self.db = db
        self.audit = audit
        self.settings = settings
        if settings.auth_provider == "supabase":
            self.provider = SupabaseAuthProvider(settings.supabase_url, settings.supabase_service_role_key)
        else:
            self.provider = DemoAuthProvider(settings.demo_jwt_secret, settings.demo_password)

    # ---------------------------------------------------------------- seed
    def seed_demo_users(self) -> None:
        for account in DEMO_ACCOUNTS:
            row = {"hospital_id": None, "jurisdiction": None, **account}
            if self.db.fetch_one("SELECT id FROM users WHERE id = :id", {"id": account["id"]}) is None:
                self.db.insert("users", {**row, "created_at": utc_now_iso()})
            else:  # built-in accounts keep their definition (their role cannot be changed)
                self.db.update(
                    "users",
                    {"role": row["role"], "hospital_id": row["hospital_id"], "jurisdiction": row["jurisdiction"]},
                    {"id": account["id"]},
                )

    def demo_accounts(self) -> List[Dict[str, Optional[str]]]:
        return [
            {
                "email": a["email"],
                "role": a["role"],
                "display_name": a["display_name"],
                "hospital_id": a.get("hospital_id"),
                "jurisdiction": a.get("jurisdiction"),
            }
            for a in DEMO_ACCOUNTS
        ]

    # --------------------------------------------------------------- login
    def _check_password(self, email: str, password: str) -> Dict[str, str]:
        """Return ``{id, email}`` for a correct email and password, or raise."""
        built_in = _BUILT_IN_BY_EMAIL.get(email)
        if built_in is not None:
            if self.provider.built_in_password_matches(password):
                return {"id": built_in["id"], "email": built_in["email"]}
            raise AuthenticationFailed("Incorrect email or password.")
        row = self.db.fetch_one(
            "SELECT u.id, u.email, c.password_hash FROM users u JOIN local_credentials c ON c.user_id = u.id "
            "WHERE u.email = :email",
            {"email": email},
        )
        # An unknown email is checked against a dummy hash so it takes as long to reject as a wrong password.
        if not verify_password(password, row["password_hash"] if row else DUMMY_HASH) or row is None:
            raise AuthenticationFailed("Incorrect email or password.")
        # Only after the right password, so the message does not reveal which emails have an account.
        self._ensure_active(row["id"])
        return {"id": row["id"], "email": row["email"]}

    def _ensure_active(self, user_id: str) -> None:
        user = self.db.fetch_one("SELECT disabled FROM users WHERE id = :id", {"id": user_id})
        if user is not None and user.get("disabled"):
            reg = self.db.fetch_one(
                "SELECT status FROM hospital_registrations WHERE user_id = :id ORDER BY created_at DESC LIMIT 1",
                {"id": user_id},
            )
            status = (reg or {}).get("status")
            if status == "PENDING":
                raise AuthenticationFailed(
                    "Your hospital's registration is waiting for an administrator's approval. You can sign in once it "
                    "is approved."
                )
            raise AuthenticationFailed("This account is not active. Contact the platform's administrator.")

    def demo_login(self, email: str, password: str) -> Dict[str, Any]:
        """Sign in with a built-in demo account or an account created through sign-up."""
        if not isinstance(self.provider, DemoAuthProvider):
            raise PermissionDenied("Demo sign-in is disabled because Supabase authentication is configured.")
        email = email.strip().lower()
        try:
            account = self._check_password(email, password)
        except AuthenticationFailed:
            self.audit.record("USER_LOGIN", email[:120] or "unknown", status="FAILED", details={"provider": "demo"})
            raise
        tokens = self.provider.issue(account["id"], account["email"])
        user = self.authenticate(tokens["access_token"])
        self.record_login(user)
        return {**tokens, "user": user}

    # ------------------------------------------------------------- sign-up
    def register(self, email: str, password: str, display_name: Optional[str] = None) -> Dict[str, Any]:
        """Create an account from the sign-up form and sign it in. The role is always viewer."""
        if not self.settings.allow_signup:
            raise PermissionDenied("Creating accounts is switched off on this server. Ask an administrator.")
        if not isinstance(self.provider, DemoAuthProvider):
            raise PermissionDenied("Accounts on this server are created through Supabase Auth, not this endpoint.")
        email = email.strip().lower()
        if len(email) > 254 or not _EMAIL.match(email):
            raise ValidationFailed("Enter a valid email address.")
        if len(password) < MIN_PASSWORD_LENGTH:
            raise ValidationFailed(f"Choose a password of at least {MIN_PASSWORD_LENGTH} characters.")
        if len(password) > MAX_PASSWORD_LENGTH:
            raise ValidationFailed(f"Choose a password of at most {MAX_PASSWORD_LENGTH} characters.")
        name = " ".join((display_name or "").split())[:80] or email.split("@")[0]
        taken = ConflictError("An account with this email already exists. Sign in instead.")
        if email in _BUILT_IN_BY_EMAIL or self.db.fetch_one("SELECT id FROM users WHERE email = :e", {"e": email}):
            raise taken

        user_id = f"local-{uuid.uuid4().hex}"
        now = utc_now_iso()
        try:
            with self.db.transaction():
                self.db.insert(
                    "users",
                    {
                        "id": user_id,
                        "email": email,
                        "display_name": name,
                        "role": DEFAULT_ROLE,
                        "hospital_id": None,
                        "created_at": now,
                    },
                )
                self.db.insert(
                    "local_credentials",
                    {"user_id": user_id, "password_hash": hash_password(password), "updated_at": now},
                )
        except DatabaseError as exc:  # two sign-ups for one email at the same moment
            if "unique" in str(exc).lower():
                raise taken from exc
            raise
        self.audit.record("USER_REGISTERED", email, details={"provider": "demo", "role": DEFAULT_ROLE})
        tokens = self.provider.issue(user_id, email)
        user = self.authenticate(tokens["access_token"])
        self.record_login(user)
        return {**tokens, "user": user}

    # ------------------------------------------------- hospital registration
    def _validate_new_credentials(self, email: str, password: str) -> None:
        if len(email) > 254 or not _EMAIL.match(email):
            raise ValidationFailed("Enter a valid email address.")
        if len(password) < MIN_PASSWORD_LENGTH:
            raise ValidationFailed(f"Choose a password of at least {MIN_PASSWORD_LENGTH} characters.")
        if len(password) > MAX_PASSWORD_LENGTH:
            raise ValidationFailed(f"Choose a password of at most {MAX_PASSWORD_LENGTH} characters.")

    def create_disabled_account(self, email: str, password: str, display_name: str) -> Dict[str, Any]:
        """The operator account of a hospital that has registered but is not approved yet: it cannot sign in."""
        if not isinstance(self.provider, DemoAuthProvider):
            raise PermissionDenied("Hospital registration needs local accounts; this server uses Supabase Auth.")
        email = email.strip().lower()
        self._validate_new_credentials(email, password)
        taken = ConflictError("An account with this email already exists. Use another contact email.")
        if email in _BUILT_IN_BY_EMAIL or self.db.fetch_one("SELECT id FROM users WHERE email = :e", {"e": email}):
            raise taken
        user_id = f"local-{uuid.uuid4().hex}"
        now = utc_now_iso()
        try:
            with self.db.transaction():
                self.db.insert(
                    "users",
                    {
                        "id": user_id,
                        "email": email,
                        "display_name": display_name[:80],
                        "role": DEFAULT_ROLE,
                        "hospital_id": None,
                        "disabled": True,
                        "created_at": now,
                    },
                )
                self.db.insert(
                    "local_credentials",
                    {"user_id": user_id, "password_hash": hash_password(password), "updated_at": now},
                )
        except DatabaseError as exc:
            if "unique" in str(exc).lower():
                raise taken from exc
            raise
        return {"id": user_id, "email": email}

    def enable_operator(self, user_id: str, hospital_id: str) -> None:
        """Approval: the account becomes this hospital's operator and may sign in."""
        self.db.update("users", {"role": "hospital", "hospital_id": hospital_id, "disabled": False}, {"id": user_id})

    def disable_account(self, user_id: str) -> None:
        self.db.update("users", {"disabled": True}, {"id": user_id})

    def authenticate(self, token: str) -> Dict[str, Any]:
        """Verify the token and return the user's row, creating it on first sight."""
        identity = self.provider.verify(token)
        user = self.db.fetch_one("SELECT * FROM users WHERE id = :id", {"id": identity.subject})
        if user is not None and user.get("disabled"):
            # A session issued before the account was disabled (for example, a revoked hospital) ends now.
            raise AuthenticationFailed("This account is not active. Contact the platform's administrator.")
        if user is None:
            role = "admin" if identity.email in self.settings.admin_emails else DEFAULT_ROLE
            user = self.db.insert(
                "users",
                {
                    "id": identity.subject,
                    "email": identity.email,
                    "display_name": identity.email.split("@")[0],
                    "role": role,
                    "hospital_id": None,
                    "created_at": utc_now_iso(),
                },
            )
        elif identity.email in self.settings.admin_emails and user["role"] != "admin":
            self.db.update("users", {"role": "admin"}, {"id": user["id"]})
            user["role"] = "admin"
        return {
            "id": user["id"],
            "email": user["email"],
            "display_name": user["display_name"],
            "role": user["role"],
            "hospital_id": user["hospital_id"],
            "jurisdiction": user.get("jurisdiction") or None,
            "provider": self.provider.name,
        }

    def record_login(self, user: Dict[str, Any]) -> None:
        self.db.update("users", {"last_login_at": utc_now_iso()}, {"id": user["id"]})
        self.audit.record("USER_LOGIN", user["email"], details={"provider": self.provider.name, "role": user["role"]})

    # ------------------------------------------------------ user management
    def _role_lock_reason(self, user: Dict[str, Any]) -> Optional[str]:
        """Why this user's role cannot be changed from the dashboard, if it cannot."""
        if user["id"] in _BUILT_IN_IDS:
            return "Built-in demo accounts keep their role."
        if user["email"] in self.settings.admin_emails:
            return "This administrator is set by ADMIN_EMAILS on the server."
        return None

    def list_users(self) -> List[Dict[str, Any]]:
        rows = self.db.fetch_all("SELECT * FROM users ORDER BY created_at, email")
        users = []
        for row in rows:
            reason = self._role_lock_reason(row)
            users.append(
                {
                    "id": row["id"],
                    "email": row["email"],
                    "display_name": row["display_name"],
                    "role": row["role"],
                    "hospital_id": row["hospital_id"],
                    "jurisdiction": row.get("jurisdiction") or None,
                    "created_at": row["created_at"],
                    "last_login_at": row["last_login_at"],
                    "built_in": row["id"] in _BUILT_IN_IDS,
                    "role_locked": reason is not None,
                    "role_locked_reason": reason,
                }
            )
        return users

    def set_role(
        self,
        actor: Dict[str, Any],
        user_id: str,
        role: str,
        hospital_id: Optional[str] = None,
        jurisdiction: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Change another user's role. Only administrators reach this (checked by the router too).

        Hospital operators and managers are linked to one hospital; health officers to a jurisdiction (one or
        more region ids); every other role to neither.
        """
        require_role(actor, ("admin",))
        if role not in ROLES:
            raise ValidationFailed(f"Role must be one of: {', '.join(ROLES)}.")
        if role in HOSPITAL_ROLES:
            if not hospital_id:
                raise ValidationFailed(f"Choose the hospital this {ROLE_LABELS[role].lower()} works for.")
            if self.db.fetch_one("SELECT id FROM hospitals WHERE id = :id", {"id": hospital_id}) is None:
                raise ValidationFailed(f"There is no hospital '{hospital_id}'.")
        else:
            hospital_id = None
        if role in JURISDICTION_ROLES:
            jurisdiction = sorted(set(jurisdiction or []))
            if not jurisdiction:
                raise ValidationFailed("Choose at least one region for this health officer's jurisdiction.")
            known = {r["region_id"] for r in self.db.fetch_all("SELECT region_id FROM regions")}
            unknown = [r for r in jurisdiction if r not in known]
            if unknown:
                raise ValidationFailed(f"Unknown region id(s): {', '.join(unknown)}.")
        else:
            jurisdiction = None
        target = self.db.fetch_one("SELECT * FROM users WHERE id = :id", {"id": user_id})
        if target is None:
            raise NotFoundError("No such user.")
        if target["id"] == actor["id"]:
            raise ConflictError("You cannot change your own role. Ask another administrator.")
        reason = self._role_lock_reason(target)
        if reason:
            raise ConflictError(reason)
        previous_jurisdiction = target.get("jurisdiction") or None
        if target["role"] != role or target["hospital_id"] != hospital_id or previous_jurisdiction != jurisdiction:
            self.db.update(
                "users", {"role": role, "hospital_id": hospital_id, "jurisdiction": jurisdiction}, {"id": user_id}
            )
            details = {"user": target["email"], "from": target["role"], "to": role}
            if role in HOSPITAL_ROLES or target["hospital_id"]:
                details.update(hospital_from=target["hospital_id"], hospital_to=hospital_id)
            if role in JURISDICTION_ROLES or previous_jurisdiction:
                details.update(jurisdiction_from=previous_jurisdiction, jurisdiction_to=jurisdiction)
            self.audit.record("USER_ROLE_CHANGED", actor["email"], details=details)
        return next(user for user in self.list_users() if user["id"] == user_id)


def require_role(user: Dict[str, Any], allowed: tuple) -> None:
    if user["role"] not in allowed:
        raise PermissionDenied(
            f"Your role ({user['role']}) does not allow this action. Required: {' or '.join(allowed)}."
        )
