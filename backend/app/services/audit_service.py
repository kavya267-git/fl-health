"""Tamper-evident audit log.

Each entry stores the hash of the previous entry and its own hash, forming a
chain: changing or removing any past entry breaks every hash after it, which
``verify_chain`` detects.

This makes tampering *detectable*, not impossible. Someone with write access to
the database could rewrite the whole chain. For stronger guarantees the latest
hash would have to be anchored somewhere the database owner cannot change.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.database import Database
from app.utils.hashing import canonical_json, sha256_hex
from app.utils.time import utc_now_iso

GENESIS_HASH = "GENESIS"

ACTIONS = (
    "USER_LOGIN",
    "USER_REGISTERED",
    "USER_ROLE_CHANGED",
    "FL_ROUND_CREATED",
    "HOSPITAL_JOINED_ROUND",
    "LOCAL_UPDATE_RECEIVED",
    "AGGREGATION_STARTED",
    "AGGREGATION_COMPLETED",
    "GLOBAL_MODEL_CREATED",
    "FL_ROUND_COMPLETED",
    "FL_ROUND_FAILED",
    "ANALYTICS_GENERATED",
    "FORECAST_GENERATED",
    "MODEL_ACCESSED",
    "HOSPITAL_STATUS_CHANGED",
    "NODE_CONNECTED",
    "HOSPITAL_DROPPED",
    "HOSPITAL_PARTICIPATION_CHANGED",
    "HOSPITAL_DECLINED_ROUND",
    "ALERT_CREATED",
    "ALERT_ACKNOWLEDGED",
    "ALERT_OUTCOME_RECORDED",
    "SITUATION_REPORT_EXPORTED",
    "HOSPITAL_CAPACITY_CHANGED",
    "PLANNING_ASSUMPTIONS_CHANGED",
    "UPDATE_FLAGGED_UNUSUAL",
)

_HASHED_FIELDS = (
    "timestamp",
    "actor",
    "action",
    "hospital_id",
    "round_id",
    "model_version",
    "status",
    "details",
    "previous_hash",
)


def _canonical_timestamp(value: Any) -> str:
    """Same text for the same instant, however the database hands it back."""
    moment = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def entry_hash(entry: Dict[str, Any]) -> str:
    hashed = {field: entry.get(field) for field in _HASHED_FIELDS}
    hashed["timestamp"] = _canonical_timestamp(hashed["timestamp"])
    hashed["details"] = hashed["details"] or {}
    return sha256_hex(canonical_json(hashed))


class AuditService:
    def __init__(self, db: Database):
        self.db = db
        self._lock = threading.Lock()

    def record(
        self,
        action: str,
        actor: str,
        status: str = "SUCCESS",
        hospital_id: Optional[str] = None,
        round_id: Optional[str] = None,
        model_version: Optional[str] = None,
        details: Optional[dict] = None,
    ) -> Dict[str, Any]:
        if action not in ACTIONS:
            raise ValueError(f"Unknown audit action '{action}'")
        # Reading the last hash and inserting must not interleave with another writer.
        with self._lock, self.db.transaction():
            last = self.db.fetch_one("SELECT current_hash FROM audit_logs ORDER BY id DESC LIMIT 1")
            entry = {
                "timestamp": utc_now_iso(),
                "actor": actor,
                "action": action,
                "hospital_id": hospital_id,
                "round_id": round_id,
                "model_version": model_version,
                "status": status,
                "details": details or {},
                "previous_hash": last["current_hash"] if last else GENESIS_HASH,
            }
            entry["current_hash"] = entry_hash(entry)
            return self.db.insert("audit_logs", entry)

    def list_entries(
        self,
        search: Optional[str] = None,
        action: Optional[str] = None,
        status: Optional[str] = None,
        hospital_id: Optional[str] = None,
        round_id: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        conditions, params = [], {}
        if action:
            conditions.append("action = :action")
            params["action"] = action
        if status:
            conditions.append("status = :status")
            params["status"] = status
        if hospital_id:
            conditions.append("hospital_id = :hospital_id")
            params["hospital_id"] = hospital_id
        if round_id:
            conditions.append("round_id = :round_id")
            params["round_id"] = round_id
        if date_from:
            conditions.append("timestamp >= :date_from")
            params["date_from"] = date_from
        if date_to:
            # A bare date means "through the end of that day".
            conditions.append("timestamp <= :date_to")
            params["date_to"] = date_to + "T23:59:59.999+00:00" if len(date_to) == 10 else date_to
        if search:
            conditions.append(
                "(LOWER(actor) LIKE :search OR LOWER(action) LIKE :search OR LOWER(COALESCE(hospital_id, '')) LIKE :search "
                "OR LOWER(COALESCE(round_id, '')) LIKE :search OR LOWER(COALESCE(model_version, '')) LIKE :search)"
            )
            params["search"] = f"%{search.lower()}%"
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        total = self.db.fetch_one(f"SELECT COUNT(*) AS n FROM audit_logs {where}", params)["n"]
        rows = self.db.fetch_all(
            f"SELECT * FROM audit_logs {where} ORDER BY id DESC LIMIT :limit OFFSET :offset",
            {**params, "limit": limit, "offset": offset},
        )
        return {"total": int(total), "items": rows}

    def recent(self, limit: int = 8) -> List[Dict[str, Any]]:
        return self.db.fetch_all("SELECT * FROM audit_logs ORDER BY id DESC LIMIT :limit", {"limit": limit})

    def verify_chain(self) -> Dict[str, Any]:
        """Recompute every hash from the first entry and report the first break, if any."""
        rows = self.db.fetch_all("SELECT * FROM audit_logs ORDER BY id ASC")
        previous = GENESIS_HASH
        for row in rows:
            if row["previous_hash"] != previous:
                return {
                    "valid": False,
                    "entries_checked": len(rows),
                    "first_invalid_id": row["id"],
                    "reason": "The link to the previous entry does not match (an entry was removed or reordered).",
                }
            if entry_hash(row) != row["current_hash"]:
                return {
                    "valid": False,
                    "entries_checked": len(rows),
                    "first_invalid_id": row["id"],
                    "reason": "The entry's content does not match its stored hash (it was modified).",
                }
            previous = row["current_hash"]
        return {
            "valid": True,
            "entries_checked": len(rows),
            "first_invalid_id": None,
            "reason": None,
            "latest_hash": previous if rows else None,
        }
