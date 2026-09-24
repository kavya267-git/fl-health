# backend/app/audit.py
import hashlib
import json
from datetime import datetime
from app.supabase_client import get_service_client


GENESIS_HASH = "GENESIS"


def compute_block_hash(previous_hash: str, entry: dict) -> str:
    payload = f"{previous_hash}|{json.dumps(entry, sort_keys=True, default=str)}"
    return hashlib.sha256(payload.encode()).hexdigest()


def get_last_hash(service) -> str:
    res = service.table("blockchain_audit").select("current_hash").order("id", desc=True).limit(1).execute()
    if res.data:
        return res.data[0]["current_hash"]
    return GENESIS_HASH


def append_audit_entry(round_number, hospital_id, hospital_name, event_type,
                       epsilon_used, model_hash, metadata=None):
    service = get_service_client()
    previous_hash = get_last_hash(service)

    entry = {
        "round_number": round_number,
        "hospital_id": hospital_id,
        "hospital_name": hospital_name,
        "event_type": event_type,
        "epsilon_used": epsilon_used,
        "model_hash": model_hash,
        "metadata": metadata or {},
        "previous_hash": previous_hash,
        "created_at": datetime.utcnow().isoformat(),
    }
    entry["current_hash"] = compute_block_hash(previous_hash, entry)

    service.table("blockchain_audit").insert(entry).execute()
    return entry


def verify_chain() -> dict:
    service = get_service_client()
    res = service.table("blockchain_audit").select("*").order("id").execute()
    entries = res.data or []

    if not entries:
        return {"valid": True, "entries": 0, "message": "Empty chain"}

    expected_prev = GENESIS_HASH
    for entry in entries:
        if entry.get("previous_hash") != expected_prev:
            return {"valid": False, "broken_at": entry.get("id"),
                    "expected": expected_prev, "found": entry.get("previous_hash")}
        expected_prev = entry.get("current_hash")

    return {"valid": True, "entries": len(entries)}


def get_audit_trail(limit: int = 100) -> list:
    service = get_service_client()
    res = service.table("blockchain_audit").select("*").order("id", desc=True).limit(limit).execute()
    return res.data or []