"""The "My hospital" page of a hospital operator: its node, its data counts, its rounds."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends

from app.routers.deps import get_ctx, hospital_operator
from app.schemas.hospitals import MyHospital
from app.services.context import AppContext
from ml.common.types import EvalResult
from ml.evaluation.metrics import metrics_from_evaluation
from ml.registry import get_adapter

router = APIRouter(prefix="/api/my-hospital", tags=["hospitals"])

_SUMMARY_KEYS = ("accuracy", "precision", "recall", "f1", "loss", "num_samples", "averaging")


def _latest_round(ctx: AppContext, hospital_id: str) -> Optional[Dict[str, Any]]:
    """This hospital's most recent round, seen from its side: its own status, timings and results only."""
    row = ctx.db.fetch_one(
        "SELECT p.*, r.round_number, r.modality, r.status AS round_status, r.config, r.started_at, r.ended_at "
        "FROM fl_participants p JOIN fl_rounds r ON r.id = p.round_id "
        "WHERE p.hospital_id = :id ORDER BY r.started_at DESC LIMIT 1",
        {"id": hospital_id},
    )
    if row is None:
        return None
    update = ctx.db.fetch_one(
        "SELECT size_bytes FROM model_updates WHERE round_id = :r AND hospital_id = :h",
        {"r": row["round_id"], "h": hospital_id},
    )
    global_on_local = None
    if row["evaluation"]:
        result = EvalResult.from_dict(row["evaluation"]["evaluation"])
        metrics = metrics_from_evaluation(result, get_adapter(row["modality"]).task)
        global_on_local = {k: metrics[k] for k in _SUMMARY_KEYS}
    local = (row["local_metrics"] or {}).get("local_validation")
    return {
        "round_id": row["round_id"],
        "round_number": row["round_number"],
        "modality": row["modality"],
        "round_status": row["round_status"],
        "status": row["status"],
        "error": row["error"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "joined_at": row["joined_at"],
        "update_received_at": row["update_received_at"],
        "evaluated_at": row["evaluated_at"],
        "num_samples": row["num_samples"],
        "update_bytes": update["size_bytes"] if update else None,
        "deadline": (row["config"] or {}).get("deadline"),
        "local_model": {k: local[k] for k in _SUMMARY_KEYS if k in local} if local else None,
        "global_model_on_local_data": global_on_local,
    }


@router.get("", response_model=MyHospital)
def my_hospital(user: Dict[str, Any] = Depends(hospital_operator), ctx: AppContext = Depends(get_ctx)):
    hospital_id = user["hospital_id"]
    return {
        "hospital": ctx.hospitals.get(hospital_id),
        "metrics": ctx.hospitals.metrics(hospital_id),
        "latest_round": _latest_round(ctx, hospital_id),
    }
