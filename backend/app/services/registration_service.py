"""Hospital registration: the public "Register your hospital" form and the administrator's review.

Lifecycle of a request::

    PENDING --approve--> APPROVED --revoke--> REVOKED
        \\--reject--> REJECTED

* **Submit** (public, no sign-in): organisation and contact details, the modalities the hospital will train on
  and approximate record counts. The operator account is created at once, **disabled**, with the password the
  hospital chose (scrypt, as for every local account). No file can be uploaded, and the form has no field for
  patient-level data.
* **Approve** (administrator): creates the hospital (``hospital_<slug>``, kind ``registered``) in the chosen
  region and enables the account as that hospital's operator.
* **Reject**: the account stays disabled; the reason is stored.
* **Revoke** (an approved hospital): disables the account and revokes the node token at once.

Every step is written to the hash-chained audit log. Registrations are visible to administrators only.
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from collections import defaultdict, deque
from typing import Any, Deque, Dict, List, Optional

from app.database import Database
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService
from app.services.hospital_service import HospitalService
from app.utils.errors import ConflictError, NotFoundError, RateLimited, ValidationFailed
from app.utils.time import utc_now_iso
from ml.common.types import MODALITIES

STATUSES = ("PENDING", "APPROVED", "REJECTED", "REVOKED")
MODALITY_LABELS = {"ehr": "EHR", "ecg": "ECG", "xray": "X-ray"}
CONFIRMATION_TEXT = "I confirm we will not upload patient data; training runs on our own machine."
MAX_RECORDS_PER_MODALITY = 10_000_000
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SLUG_CHARS = re.compile(r"[^a-z0-9]+")
#: hospital_a .. hospital_d are the built-in (simulated) hospitals; a registration never takes their ids.
RESERVED_IDS = {f"hospital_{letter}" for letter in "abcd"}


class RateLimiter:
    """Sliding-window limit per key, plus a global cap so changing IP addresses cannot flood the queue."""

    def __init__(self, per_key: int, global_limit: int, window_seconds: float, clock=time.monotonic):
        self.per_key = per_key
        self.global_limit = global_limit
        self.window = window_seconds
        self._clock = clock
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._all: Deque[float] = deque()
        self._lock = threading.Lock()

    def _trim(self, hits: Deque[float], now: float) -> None:
        while hits and now - hits[0] >= self.window:
            hits.popleft()

    def check(self, key: str) -> None:
        with self._lock:
            now = self._clock()
            hits = self._hits[key]
            self._trim(hits, now)
            self._trim(self._all, now)
            if len(hits) >= self.per_key or len(self._all) >= self.global_limit:
                raise RateLimited("Too many registration requests. Try again in an hour.")
            hits.append(now)
            self._all.append(now)


def _clean_text(value: Any, field: str, max_length: int, min_length: int = 2) -> str:
    text = " ".join(str(value or "").split())
    if len(text) < min_length:
        raise ValidationFailed(f"Enter the {field}.")
    if len(text) > max_length:
        raise ValidationFailed(f"The {field} must be at most {max_length} characters.")
    if any(ord(ch) < 32 for ch in text):
        raise ValidationFailed(f"The {field} contains characters that are not allowed.")
    return text


def slugify(name: str) -> str:
    slug = _SLUG_CHARS.sub("_", name.lower()).strip("_")
    return slug[:40].strip("_") or "hospital"


class RegistrationService:
    def __init__(
        self,
        db: Database,
        audit: AuditService,
        auth: AuthService,
        hospitals: HospitalService,
        per_ip_per_hour: int = 5,
        global_per_hour: int = 60,
    ):
        self.db = db
        self.audit = audit
        self.auth = auth
        self.hospitals = hospitals
        self.limiter = RateLimiter(per_ip_per_hour, global_per_hour, 3600.0)

    # --------------------------------------------------------------- public
    def regions(self) -> List[Dict[str, str]]:
        """Region ids and names only, for the form's region list."""
        return [
            {"region_id": r["region_id"], "name": r["name"]}
            for r in self.db.fetch_all("SELECT region_id, name FROM regions ORDER BY name")
        ]

    def submit(self, payload: Dict[str, Any], client_key: str) -> Dict[str, Any]:
        """Validate and store a request; create the operator account, disabled. Returns a receipt."""
        self.limiter.check(client_key)
        hospital_name = _clean_text(payload.get("hospital_name"), "hospital name", 120)
        contact_name = _clean_text(payload.get("contact_name"), "contact name", 80)
        email = str(payload.get("contact_email") or "").strip().lower()
        if len(email) > 254 or not _EMAIL.match(email):
            raise ValidationFailed("Enter a valid contact email address.")
        region_id = str(payload.get("region_id") or "")
        if self.db.fetch_one("SELECT region_id FROM regions WHERE region_id = :r", {"r": region_id}) is None:
            raise ValidationFailed("Choose a region from the list.")
        modalities = payload.get("modalities") or []
        if not isinstance(modalities, list) or not modalities:
            raise ValidationFailed("Choose at least one kind of data (EHR, ECG or X-ray).")
        if any(m not in MODALITIES for m in modalities) or len(set(modalities)) != len(modalities):
            raise ValidationFailed(f"Modalities must be among: {', '.join(MODALITIES)}, each at most once.")
        modalities = [m for m in MODALITIES if m in modalities]
        counts_in = payload.get("approx_record_counts") or {}
        if not isinstance(counts_in, dict) or set(counts_in) - set(modalities):
            raise ValidationFailed("Give an approximate record count for each chosen kind of data, and no other.")
        counts: Dict[str, int] = {}
        for modality in modalities:
            value = counts_in.get(modality)
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_RECORDS_PER_MODALITY:
                raise ValidationFailed(
                    f"Enter an approximate number of {MODALITY_LABELS[modality]} records between 1 and "
                    f"{MAX_RECORDS_PER_MODALITY:,}."
                )
            counts[modality] = value
        if payload.get("confirm_no_patient_data") is not True:
            raise ValidationFailed(f"Tick the box: “{CONFIRMATION_TEXT}”")
        password = payload.get("password") or ""
        if password != (payload.get("password_confirm") or ""):
            raise ValidationFailed("The two passwords do not match.")
        if self.db.fetch_one(
            "SELECT id FROM hospital_registrations WHERE LOWER(hospital_name) = :n AND status IN ('PENDING', 'APPROVED')",
            {"n": hospital_name.lower()},
        ):
            raise ConflictError("A hospital with this name is already registered or waiting for approval.")

        user = self.auth.create_disabled_account(email, password, contact_name)
        registration_id = f"reg-{uuid.uuid4().hex[:12]}"
        now = utc_now_iso()
        self.db.insert(
            "hospital_registrations",
            {
                "id": registration_id,
                "hospital_name": hospital_name,
                "region_id": region_id,
                "contact_name": contact_name,
                "contact_email": email,
                "modalities": modalities,
                "approx_record_counts": counts,
                "status": "PENDING",
                "user_id": user["id"],
                "hospital_id": None,
                "reviewed_by": None,
                "reviewed_at": None,
                "reason": None,
                "created_at": now,
            },
        )
        self.audit.record(
            "HOSPITAL_REGISTRATION_SUBMITTED",
            email,
            details={"registration": registration_id, "hospital_name": hospital_name, "region_id": region_id,
                     "modalities": modalities},
        )
        return {"id": registration_id, "status": "PENDING", "hospital_name": hospital_name, "submitted_at": now}

    # ---------------------------------------------------------------- admin
    def list(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        if status is not None and status not in STATUSES:
            raise ValidationFailed(f"Status must be one of: {', '.join(STATUSES)}.")
        rows = self.db.fetch_all(
            "SELECT * FROM hospital_registrations"
            + (" WHERE status = :s" if status else "")
            + " ORDER BY created_at DESC",
            {"s": status} if status else None,
        )
        regions = {r["region_id"]: r["name"] for r in self.regions()}
        return [{**row, "region_name": regions.get(row["region_id"])} for row in rows]

    def pending_count(self) -> int:
        row = self.db.fetch_one("SELECT COUNT(*) AS n FROM hospital_registrations WHERE status = 'PENDING'")
        return int(row["n"])

    def _get(self, registration_id: str) -> Dict[str, Any]:
        row = self.db.fetch_one("SELECT * FROM hospital_registrations WHERE id = :id", {"id": registration_id})
        if row is None:
            raise NotFoundError("No such registration.")
        return row

    def _unique_hospital_id(self, name: str) -> str:
        base = f"hospital_{slugify(name)}"
        candidate, n = base, 2
        while candidate in RESERVED_IDS or self.db.fetch_one("SELECT id FROM hospitals WHERE id = :id", {"id": candidate}):
            candidate = f"{base}_{n}"
            n += 1
        return candidate

    def approve(self, registration_id: str, actor: Dict[str, Any]) -> Dict[str, Any]:
        with self.db.transaction():
            row = self._get(registration_id)
            if row["status"] != "PENDING":
                raise ConflictError(f"This request is {row['status'].lower()}; only pending requests can be approved.")
            hospital_id = self._unique_hospital_id(row["hospital_name"])
            self.hospitals.create_registered(hospital_id, row["hospital_name"], row["region_id"], row["modalities"])
            self.auth.enable_operator(row["user_id"], hospital_id)
            now = utc_now_iso()
            self.db.update(
                "hospital_registrations",
                {"status": "APPROVED", "hospital_id": hospital_id, "reviewed_by": actor["email"], "reviewed_at": now},
                {"id": registration_id},
            )
        self.audit.record(
            "HOSPITAL_REGISTRATION_APPROVED",
            actor["email"],
            hospital_id=hospital_id,
            details={"registration": registration_id, "hospital_name": row["hospital_name"], "operator": row["contact_email"]},
        )
        return self._get(registration_id)

    def reject(self, registration_id: str, reason: str, actor: Dict[str, Any]) -> Dict[str, Any]:
        reason = _clean_text(reason, "reason", 500, min_length=3)
        row = self._get(registration_id)
        if row["status"] != "PENDING":
            raise ConflictError(f"This request is {row['status'].lower()}; only pending requests can be rejected.")
        self.db.update(
            "hospital_registrations",
            {"status": "REJECTED", "reviewed_by": actor["email"], "reviewed_at": utc_now_iso(), "reason": reason},
            {"id": registration_id},
        )
        self.audit.record(
            "HOSPITAL_REGISTRATION_REJECTED",
            actor["email"],
            details={"registration": registration_id, "hospital_name": row["hospital_name"], "reason": reason},
        )
        return self._get(registration_id)

    def revoke(self, registration_id: str, reason: str, actor: Dict[str, Any]) -> Dict[str, Any]:
        """Take an approved hospital out: its operator can no longer sign in and its node token stops working."""
        reason = _clean_text(reason, "reason", 500, min_length=3)
        row = self._get(registration_id)
        if row["status"] != "APPROVED":
            raise ConflictError(f"This request is {row['status'].lower()}; only approved hospitals can be revoked.")
        with self.db.transaction():
            self.auth.disable_account(row["user_id"])
            self.hospitals.revoke_node_token(row["hospital_id"])
            self.hospitals.set_registered_active(row["hospital_id"], False)
            self.db.update(
                "hospital_registrations",
                {"status": "REVOKED", "reviewed_by": actor["email"], "reviewed_at": utc_now_iso(), "reason": reason},
                {"id": registration_id},
            )
        self.audit.record(
            "HOSPITAL_REGISTRATION_REVOKED",
            actor["email"],
            hospital_id=row["hospital_id"],
            details={"registration": registration_id, "hospital_name": row["hospital_name"], "reason": reason},
        )
        return self._get(registration_id)
