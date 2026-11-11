"""Hospital metadata and per-hospital metrics.

Only metadata is held centrally: name, availability, which modalities a
hospital has, and record *counts* reported by the hospital node.

Availability depends on how the hospitals run. With in-process nodes it is the
``online`` flag a coordinator can toggle (to demonstrate partial
participation). With external nodes it comes from the nodes themselves: a
hospital is online while its node keeps sending heartbeats.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.database import Database
from app.services.audit_service import AuditService
from app.utils.errors import ConflictError, NotFoundError, PermissionDenied, ValidationFailed
from app.utils.hashing import constant_time_equal, hmac_token
from app.utils.time import utc_now, utc_now_iso

#: Nodes send a heartbeat every ~10 s; three missed beats means disconnected.
HEARTBEAT_TIMEOUT_SECONDS = 30
#: Hospitals created by approving a public registration. They run their own node and use a per-hospital token.
REGISTERED = "registered"
#: Fields of a node's local data check that may reach the coordinator (pass / fail and counts only).
_CHECK_FIELDS = ("passed", "train_records", "val_records", "label_counts", "problems")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class HospitalService:
    def __init__(
        self, db: Database, audit: AuditService, node_token_secret: str, hospital_nodes: str = "in-process"
    ):
        self.db = db
        self.audit = audit
        self._node_token_secret = node_token_secret
        self.external_nodes = hospital_nodes == "external"

    # ----------------------------------------------------------------- seed
    def upsert(
        self,
        hospital_id: str,
        name: str,
        kind: str,
        modalities: List[str],
        data_summary: Optional[dict],
        is_simulated: bool,
    ) -> None:
        existing = self.db.fetch_one("SELECT id FROM hospitals WHERE id = :id", {"id": hospital_id})
        if existing:
            self.db.update(
                "hospitals",
                {
                    "name": name,
                    "kind": kind,
                    "modalities": modalities,
                    "data_summary": data_summary,
                    "is_simulated": is_simulated,
                },
                {"id": hospital_id},
            )
            return
        self.db.insert(
            "hospitals",
            {
                "id": hospital_id,
                "name": name,
                "kind": kind,
                "online": True,
                "modalities": modalities,
                "data_summary": data_summary,
                "is_simulated": is_simulated,
                "created_at": utc_now_iso(),
            },
        )

    # --------------------------------------------------------------- lookup
    def list_raw(self) -> List[Dict[str, Any]]:
        return self._with_presence(self.db.fetch_all("SELECT * FROM hospitals ORDER BY id"))

    def get_raw(self, hospital_id: str) -> Dict[str, Any]:
        row = self.db.fetch_one("SELECT * FROM hospitals WHERE id = :id", {"id": hospital_id})
        if row is None:
            raise NotFoundError(f"Hospital '{hospital_id}' does not exist")
        return self._with_presence([row])[0]

    # ------------------------------------------------------------ presence
    @staticmethod
    def _is_fresh(last_seen_at: Any, now: Optional[datetime] = None) -> bool:
        if not last_seen_at:
            return False
        seen = last_seen_at if isinstance(last_seen_at, datetime) else datetime.fromisoformat(str(last_seen_at))
        return (now or utc_now()) - seen <= timedelta(seconds=HEARTBEAT_TIMEOUT_SECONDS)

    def _with_presence(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Add participation, and with external nodes, presence: online while the node's heartbeat is fresh."""
        settings = {s["hospital_id"]: s for s in self.db.fetch_all("SELECT * FROM hospital_settings")}
        for row in rows:
            # Hospitals take part unless their operator has switched it off.
            row["participating"] = bool(settings.get(row["id"], {}).get("participating", True))
        if not self.external_nodes:
            for row in rows:
                row["node"] = None
            return rows
        beats = {b["hospital_id"]: b for b in self.db.fetch_all("SELECT * FROM node_heartbeats")}
        now = utc_now()
        for row in rows:
            beat = beats.get(row["id"])
            connected = beat is not None and self._is_fresh(beat["last_seen_at"], now)
            row["online"] = connected
            row["node"] = (
                None
                if beat is None
                else {
                    "connected": connected,
                    "last_seen_at": beat["last_seen_at"],
                    "connected_since": beat["connected_since"] if connected else None,
                    "hostname": beat["hostname"],
                    "ml_backend": beat["ml_backend"],
                    "device": beat["device"],
                    "software_version": beat["software_version"],
                }
            )
        return rows

    def record_heartbeat(self, hospital_id: str, beat: Dict[str, Any]) -> Dict[str, Any]:
        """Store a node's heartbeat. ``data_summary`` holds record counts only."""
        hospital = self.get_raw(hospital_id)
        existing = self.db.fetch_one("SELECT * FROM node_heartbeats WHERE hospital_id = :id", {"id": hospital_id})
        reconnected = existing is None or not self._is_fresh(existing["last_seen_at"])
        now = utc_now_iso()
        values = {
            "hostname": beat.get("hostname"),
            "ml_backend": beat.get("ml_backend"),
            "device": beat.get("device"),
            "software_version": beat.get("software_version"),
            "architectures": beat.get("architectures"),
            "data_summary": beat.get("data_summary"),
            "last_seen_at": now,
        }
        if reconnected:
            values["connected_since"] = now
        if existing is None:
            self.db.insert("node_heartbeats", {"hospital_id": hospital_id, **values})
        else:
            self.db.update("node_heartbeats", values, {"hospital_id": hospital_id})
        summary = beat.get("data_summary")
        if summary:
            simulated = all(entry.get("simulated", False) for entry in summary.values())
            self.db.update(
                "hospitals",
                {"data_summary": summary, "modalities": self._eligible(hospital, summary), "is_simulated": simulated},
                {"id": hospital_id},
            )
        if reconnected:
            self.audit.record(
                "NODE_CONNECTED",
                hospital_id,
                hospital_id=hospital_id,
                details={
                    "hostname": beat.get("hostname"),
                    "ml_backend": beat.get("ml_backend"),
                    "device": beat.get("device"),
                    "software_version": beat.get("software_version"),
                    "hospital": hospital["name"],
                },
            )
        return {
            "hospital_id": hospital_id,
            "received_at": now,
            "timeout_seconds": HEARTBEAT_TIMEOUT_SECONDS,
            "participating": hospital["participating"],
        }

    # -------------------------------------------------------- participation
    def set_participation(self, hospital_id: str, participating: bool, actor: str) -> Dict[str, Any]:
        """The operator's "Take part in future rounds" switch. Audited both ways."""
        hospital = self.get_raw(hospital_id)
        now = utc_now_iso()
        if hospital["participating"] != participating:
            values = {"participating": participating, "updated_at": now, "updated_by": actor}
            if self.db.fetch_one("SELECT hospital_id FROM hospital_settings WHERE hospital_id = :id", {"id": hospital_id}):
                self.db.update("hospital_settings", values, {"hospital_id": hospital_id})
            else:
                self.db.insert("hospital_settings", {"hospital_id": hospital_id, **values})
            self.audit.record(
                "HOSPITAL_PARTICIPATION_CHANGED",
                actor,
                hospital_id=hospital_id,
                details={"participating": participating, "hospital": hospital["name"]},
            )
        return self.get(hospital_id)

    def _enrich(self, hospital: Dict[str, Any]) -> Dict[str, Any]:
        hospital_id = hospital["id"]
        current = self.db.fetch_one(
            "SELECT r.id, r.modality, r.status, p.status AS participant_status FROM fl_participants p "
            "JOIN fl_rounds r ON r.id = p.round_id WHERE p.hospital_id = :id "
            "AND r.status NOT IN ('COMPLETED', 'FAILED') ORDER BY r.started_at DESC LIMIT 1",
            {"id": hospital_id},
        )
        latest_update = self.db.fetch_one(
            "SELECT round_id, modality, status, num_samples, received_at FROM model_updates "
            "WHERE hospital_id = :id ORDER BY received_at DESC LIMIT 1",
            {"id": hospital_id},
        )
        participation = self.db.fetch_one(
            "SELECT COUNT(*) AS n FROM fl_participants p JOIN fl_rounds r ON r.id = p.round_id "
            "WHERE p.hospital_id = :id AND r.status = 'COMPLETED' AND p.status IN ('EVALUATED', 'UPDATE_SUBMITTED', 'EVALUATION_FAILED')",
            {"id": hospital_id},
        )
        return {
            "id": hospital_id,
            "name": hospital["name"],
            "kind": hospital["kind"],
            "online": hospital["online"],
            "modalities": hospital["modalities"] or [],
            "data_summary": hospital["data_summary"] or {},
            "is_simulated": hospital["is_simulated"],
            "last_activity_at": hospital["last_activity_at"],
            "current_round": current,
            "latest_update": latest_update,
            "rounds_completed": int(participation["n"]),
            "fl_participation": (
                "PARTICIPATING"
                if current
                else "OPTED_OUT"
                if not hospital["participating"]
                else ("IDLE" if hospital["online"] else "UNAVAILABLE")
            ),
            "participating": hospital["participating"],
            "node_mode": "external" if self.external_nodes else "in-process",
            "node": hospital["node"],
        }

    def list(self) -> List[Dict[str, Any]]:
        return [self._enrich(row) for row in self.list_raw()]

    def get(self, hospital_id: str) -> Dict[str, Any]:
        return self._enrich(self.get_raw(hospital_id))

    def metrics(self, hospital_id: str) -> Dict[str, Any]:
        self.get_raw(hospital_id)
        rows = self.db.fetch_all(
            "SELECT m.*, r.round_number FROM training_metrics m JOIN fl_rounds r ON r.id = m.round_id "
            "WHERE m.hospital_id = :id ORDER BY m.id",
            {"id": hospital_id},
        )
        rounds = self.db.fetch_all(
            "SELECT p.round_id, p.status, p.num_samples, p.error, p.update_received_at, r.modality, "
            "r.round_number, r.status AS round_status FROM fl_participants p JOIN fl_rounds r ON r.id = p.round_id "
            "WHERE p.hospital_id = :id ORDER BY r.started_at DESC LIMIT 30",
            {"id": hospital_id},
        )
        return {
            "hospital_id": hospital_id,
            "local_training": [r for r in rows if r["scope"] == "local" and r["split"] == "train"],
            "local_validation": [r for r in rows if r["scope"] == "local" and r["split"] == "val"],
            "global_model_on_local_data": [r for r in rows if r["scope"] == "global_per_hospital"],
            "participation": rounds,
        }

    # --------------------------------------------------------- availability
    def set_online(self, hospital_id: str, online: bool, actor: str) -> Dict[str, Any]:
        if self.external_nodes:
            raise ConflictError(
                "Hospital nodes run on their own machines, so availability comes from their heartbeat. "
                "Stop or start the node on the hospital's machine instead."
            )
        if self.get_raw(hospital_id)["kind"] == REGISTERED:
            raise ConflictError(
                "A registered hospital runs its own node and joins only when this server uses external nodes "
                "(HOSPITAL_NODES=external)."
            )
        self.db.update("hospitals", {"online": online, "last_activity_at": utc_now_iso()}, {"id": hospital_id})
        self.audit.record("HOSPITAL_STATUS_CHANGED", actor, hospital_id=hospital_id, details={"online": online})
        return self.get(hospital_id)

    # ------------------------------------------------------------ node auth
    def node_token(self, hospital_id: str) -> str:
        """The HMAC token of a built-in hospital (hospital_a-d), derived from NODE_TOKEN_SECRET."""
        return hmac_token(self._node_token_secret, f"hospital-node:{hospital_id}")

    def verify_node_token(self, hospital_id: str, token: str) -> bool:
        """Registered hospitals: the hash of their current, unrevoked token. Built-in ones: the HMAC token."""
        if not token:
            return False
        hospital = self.db.fetch_one("SELECT kind FROM hospitals WHERE id = :id", {"id": hospital_id})
        if hospital is not None and hospital["kind"] == REGISTERED:
            row = self.db.fetch_one("SELECT token_hash, revoked_at FROM node_tokens WHERE hospital_id = :id", {"id": hospital_id})
            return row is not None and row["revoked_at"] is None and constant_time_equal(row["token_hash"], _token_hash(token))
        return constant_time_equal(self.node_token(hospital_id), token)

    def issue_node_token(self, hospital_id: str, actor: str) -> Dict[str, Any]:
        """A new random token for a registered hospital, returned once. Any earlier token stops working at once."""
        hospital = self.get_raw(hospital_id)
        if hospital["kind"] != REGISTERED:
            raise ConflictError(
                "This built-in hospital uses the token derived from the server's NODE_TOKEN_SECRET "
                "(scripts/node_token.py on the server)."
            )
        token = secrets.token_urlsafe(32)
        now = utc_now_iso()
        values = {"token_hash": _token_hash(token), "created_by": actor, "created_at": now, "revoked_at": None}
        replaced = self.db.fetch_one("SELECT hospital_id FROM node_tokens WHERE hospital_id = :id", {"id": hospital_id})
        if replaced:
            self.db.update("node_tokens", values, {"hospital_id": hospital_id})
        else:
            self.db.insert("node_tokens", {"hospital_id": hospital_id, **values})
        self.audit.record(
            "NODE_TOKEN_ISSUED", actor, hospital_id=hospital_id, details={"replaced_previous_token": bool(replaced)}
        )
        return {"hospital_id": hospital_id, "token": token, "created_at": now, "replaced_previous_token": bool(replaced)}

    def hospital_for_token(self, token: str) -> Optional[str]:
        """The registered hospital whose current token this is (lets the agent work from the token alone)."""
        if not token:
            return None
        row = self.db.fetch_one(
            "SELECT hospital_id FROM node_tokens WHERE token_hash = :h AND revoked_at IS NULL", {"h": _token_hash(token)}
        )
        return row["hospital_id"] if row else None

    def revoke_node_token(self, hospital_id: Optional[str]) -> None:
        if hospital_id:
            self.db.execute(
                "UPDATE node_tokens SET revoked_at = :now WHERE hospital_id = :id AND revoked_at IS NULL",
                {"now": utc_now_iso(), "id": hospital_id},
            )

    def token_status(self, hospital_id: str) -> Optional[Dict[str, Any]]:
        row = self.db.fetch_one(
            "SELECT created_at, created_by, revoked_at FROM node_tokens WHERE hospital_id = :id", {"id": hospital_id}
        )
        return dict(row) if row else None

    # ---------------------------------------------------- registered hospitals
    def create_registered(self, hospital_id: str, name: str, region_id: str, declared: List[str]) -> None:
        """An approved registration. Offline (and invited to nothing) until its own node connects."""
        self.db.insert(
            "hospitals",
            {
                "id": hospital_id,
                "name": name,
                "kind": REGISTERED,
                "online": False,
                "modalities": [],
                "data_summary": {},
                "is_simulated": False,
                "region_id": region_id,
                "declared_modalities": list(declared),
                "data_check": {},
                "created_at": utc_now_iso(),
            },
        )

    def set_registered_active(self, hospital_id: Optional[str], active: bool) -> None:
        """A revoked hospital is invited to nothing, even if a stale heartbeat is still fresh."""
        if hospital_id and not active:
            self.db.update("hospitals", {"modalities": [], "online": False}, {"id": hospital_id})
            self.db.execute("DELETE FROM node_heartbeats WHERE hospital_id = :id", {"id": hospital_id})

    def _eligible(self, hospital: Dict[str, Any], summary: Dict[str, Any]) -> List[str]:
        """Modalities a hospital is invited to. A registered one: declared AND its local data check passed AND present."""
        present = set(summary)
        if hospital.get("kind") != REGISTERED:
            return sorted(present)
        declared = set(hospital.get("declared_modalities") or [])
        passed = {m for m, c in (hospital.get("data_check") or {}).items() if c.get("passed")}
        return sorted(present & declared & passed)

    def record_data_check(self, hospital_id: str, check: Dict[str, Any]) -> Dict[str, Any]:
        """A node's local data check: pass / fail and counts per modality. Nothing else is kept."""
        hospital = self.get_raw(hospital_id)
        if hospital["kind"] != REGISTERED:
            raise ConflictError("Data checks are reported by registered hospitals only.")
        clean: Dict[str, dict] = {}
        for modality, entry in (check or {}).items():
            if modality not in (hospital.get("declared_modalities") or []) or not isinstance(entry, dict):
                continue
            try:
                clean[modality] = {
                    "passed": bool(entry.get("passed")),
                    "train_records": max(0, int(entry.get("train_records", 0))),
                    "val_records": max(0, int(entry.get("val_records", 0))),
                    "label_counts": {str(k)[:12]: max(0, int(v)) for k, v in (entry.get("label_counts") or {}).items()}
                    if isinstance(entry.get("label_counts"), dict) and len(entry.get("label_counts")) <= 8
                    else {},
                    "problems": [str(p)[:200] for p in (entry.get("problems") or [])][:10],
                    "checked_at": utc_now_iso(),
                }
            except (TypeError, ValueError) as exc:
                raise ValidationFailed(f"Invalid data check for {modality}: {exc}") from exc
        self.db.update("hospitals", {"data_check": clean}, {"id": hospital_id})
        hospital = self.get_raw(hospital_id)
        self.db.update(
            "hospitals",
            {"modalities": self._eligible(hospital, hospital.get("data_summary") or {})},
            {"id": hospital_id},
        )
        self.audit.record(
            "NODE_DATA_CHECK_REPORTED",
            hospital_id,
            hospital_id=hospital_id,
            details={m: {"passed": c["passed"], "train_records": c["train_records"], "val_records": c["val_records"]}
                     for m, c in clean.items()},
        )
        return {"hospital_id": hospital_id, "data_check": clean, "invited_modalities": self.get_raw(hospital_id)["modalities"]}

    def node_profile(self, hospital_id: str) -> Dict[str, Any]:
        """What setup_hospital.py needs to know: the hospital's name and the modalities it declared."""
        hospital = self.get_raw(hospital_id)
        registered = hospital["kind"] == REGISTERED
        return {
            "hospital_id": hospital_id,
            "name": hospital["name"],
            "registered": registered,
            "region_id": hospital.get("region_id"),
            "declared_modalities": (hospital.get("declared_modalities") or []) if registered else list(hospital["modalities"] or []),
        }

    def ensure_not_registered(self, hospital_id: str) -> None:
        if self.get_raw(hospital_id)["kind"] == REGISTERED:
            raise PermissionDenied("A registered hospital's availability comes from its own node.")
