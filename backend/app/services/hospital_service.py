"""Hospital metadata and per-hospital metrics.

Only metadata is held centrally: name, availability, which modalities a
hospital has, and record *counts* reported by the hospital node.

Availability depends on how the hospitals run. With in-process nodes it is the
``online`` flag a coordinator can toggle (to demonstrate partial
participation). With external nodes it comes from the nodes themselves: a
hospital is online while its node keeps sending heartbeats.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.database import Database
from app.services.audit_service import AuditService
from app.utils.errors import ConflictError, NotFoundError
from app.utils.hashing import constant_time_equal, hmac_token
from app.utils.time import utc_now, utc_now_iso

#: Nodes send a heartbeat every ~10 s; three missed beats means disconnected.
HEARTBEAT_TIMEOUT_SECONDS = 30


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
        """With external nodes, a hospital is online while its node's heartbeat is fresh."""
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
                {"data_summary": summary, "modalities": sorted(summary), "is_simulated": simulated},
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
        return {"hospital_id": hospital_id, "received_at": now, "timeout_seconds": HEARTBEAT_TIMEOUT_SECONDS}

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
            "fl_participation": "PARTICIPATING" if current else ("IDLE" if hospital["online"] else "UNAVAILABLE"),
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
        self.get_raw(hospital_id)
        self.db.update("hospitals", {"online": online, "last_activity_at": utc_now_iso()}, {"id": hospital_id})
        self.audit.record("HOSPITAL_STATUS_CHANGED", actor, hospital_id=hospital_id, details={"online": online})
        return self.get(hospital_id)

    # ------------------------------------------------------------ node auth
    def node_token(self, hospital_id: str) -> str:
        """The shared secret a hospital node presents in ``X-Hospital-Token``."""
        return hmac_token(self._node_token_secret, f"hospital-node:{hospital_id}")

    def verify_node_token(self, hospital_id: str, token: str) -> bool:
        return bool(token) and constant_time_equal(self.node_token(hospital_id), token)
