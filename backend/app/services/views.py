"""Read models: assemble what the API returns from several services."""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.federated import coordinator as rounds
from app.services.context import AppContext
from app.services.model_registry import STATUS_INITIAL
from app.services.permissions import AUDIT_READER_ROLES, HOSPITAL_ROLES
from app.utils.errors import ServiceError
from ml.common.types import MODALITIES
from ml.registry import get_adapter

_METRIC_KEYS = ("accuracy", "precision", "recall", "f1", "loss")


def sanitize_data_summary(summary: Optional[dict]) -> Dict[str, dict]:
    """Keep only the documented count/provenance fields a node may report."""
    clean: Dict[str, dict] = {}
    for modality in MODALITIES:
        entry = (summary or {}).get(modality)
        if not isinstance(entry, dict):
            continue
        try:
            clean[modality] = {
                "source": str(entry.get("source", "unknown"))[:40],
                "simulated": bool(entry.get("simulated", False)),
                "description": str(entry.get("description", ""))[:240],
                "train_samples": max(0, int(entry.get("train_samples", 0))),
                "val_samples": max(0, int(entry.get("val_samples", 0))),
            }
        except (TypeError, ValueError):
            continue
    return clean


def round_detail(ctx: AppContext, round_id: str, viewer: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    row = ctx.coordinator.get_round(round_id)
    participants = ctx.coordinator.participants(round_id)
    own = viewer.get("hospital_id") if viewer and viewer.get("role") in HOSPITAL_ROLES else None
    for participant in participants:
        participant.pop("evaluation", None)  # raw confusion matrices are available via /metrics
        if own and participant["hospital_id"] != own:
            # A hospital operator sees every hospital's progress, but only its own local results.
            participant["local_metrics"] = None
            if participant["status"] != rounds.P_DROPPED:  # deadline reasons come from the coordinator
                participant["error"] = None
    submitted = (rounds.P_SUBMITTED, rounds.P_EVALUATED, rounds.P_EVALUATION_FAILED)
    expected = [p for p in participants if p["status"] not in (rounds.P_DROPPED, rounds.P_FAILED, rounds.P_REJECTED)]
    return {
        **row,
        "participants": participants,
        "updates_received": sum(1 for p in participants if p["status"] in submitted),
        "updates_expected": len(expected),
        "evaluations_received": sum(1 for p in participants if p["status"] == rounds.P_EVALUATED),
    }


def model_detail(ctx: AppContext, modality: str) -> Dict[str, Any]:
    summary = ctx.registry.describe(modality)
    versions = [
        {
            "version": v["version"],
            "status": v["status"],
            "architecture": v["architecture"],
            "backend": v["backend"],
            "round_id": v["round_id"],
            "created_at": v["created_at"],
            "weights_sha256": v["weights_sha256"],
            "weights_available": bool(v["weights_path"]),
            "size_bytes": v["size_bytes"],
            "metrics": None if not v["metrics"] else {k: v["metrics"].get(k) for k in _METRIC_KEYS + ("num_samples",)},
        }
        for v in ctx.registry.versions(modality)
    ]
    return {**summary, "versions": versions}


def model_metrics(ctx: AppContext, modality: str) -> Dict[str, Any]:
    summary = ctx.registry.describe(modality)
    current_signature = summary["architecture_signature"]
    series = []
    for version in reversed(ctx.registry.versions(modality)):
        # Only versions of the current architecture belong on one chart.
        if version["status"] == STATUS_INITIAL or not version["metrics"]:
            continue
        if version["architecture_signature"] != current_signature:
            continue
        round_row = ctx.db.fetch_one("SELECT round_number FROM fl_rounds WHERE id = :id", {"id": version["round_id"]})
        series.append(
            {
                "version": version["version"],
                "round_id": version["round_id"],
                "round_number": round_row["round_number"] if round_row else None,
                **{k: float(version["metrics"][k]) for k in _METRIC_KEYS},
                "num_samples": int(version["metrics"]["num_samples"]),
                "created_at": version["created_at"],
            }
        )
    round_ids = [point["round_id"] for point in series]
    local_rows = ctx.db.fetch_all(
        "SELECT m.round_id, m.hospital_id, m.split, m.metrics, m.num_samples, r.round_number "
        "FROM training_metrics m JOIN fl_rounds r ON r.id = m.round_id "
        "WHERE m.modality = :modality AND m.scope = 'local' ORDER BY m.id",
        {"modality": modality},
    )
    local = [
        {
            "round_id": row["round_id"],
            "round_number": row["round_number"],
            "hospital_id": row["hospital_id"],
            "split": row["split"],
            "loss": row["metrics"].get("loss"),
            "accuracy": row["metrics"].get("accuracy"),
            "f1": row["metrics"].get("f1"),
            "num_samples": row["num_samples"],
        }
        for row in local_rows
        if row["round_id"] in round_ids
    ]
    latest = summary["latest_metrics"]
    return {
        "model_id": modality,
        "architecture": summary["architecture"],
        "backend": summary["backend"],
        "task": summary["task"],
        "dataset": summary["dataset"],
        "series": series,
        "local_training": local,
        "latest": None
        if not latest
        else {
            "version": summary["current_version"],
            "per_class": latest.get("per_class"),
            "confusion": latest.get("confusion"),
            "averaging": latest.get("averaging"),
            "evaluated_hospitals": latest.get("evaluated_hospitals"),
        },
        "is_simulated": summary["is_simulated"],
    }


def _model_card(ctx: AppContext, modality: str) -> Dict[str, Any]:
    try:
        summary = ctx.registry.describe(modality)
    except ServiceError as exc:
        adapter_error = exc.message
        return {"modality": modality, "available": False, "reason": adapter_error}
    metrics = summary["latest_metrics"] or {}
    return {
        "modality": modality,
        "available": True,
        "architecture": summary["architecture"],
        "backend": summary["backend"],
        "is_target_architecture": summary["is_target_architecture"],
        "target_architecture": summary["target_architecture"],
        "current_version": summary["current_version"],
        "training_status": summary["training_status"],
        "primary_metric": summary["task"]["primary_metric"],
        "task_name": summary["task"]["name"],
        "metrics": {k: metrics.get(k) for k in _METRIC_KEYS} if metrics else None,
        "evaluation_samples": metrics.get("num_samples"),
        "last_updated": summary["last_updated"],
        "is_simulated": summary["is_simulated"],
    }


def overview(ctx: AppContext, user: Dict[str, Any]) -> Dict[str, Any]:
    """Everything the main dashboard shows, in one response.

    ``recent_activity`` comes from the audit log, so it is filled only for roles that may read the audit log
    and is None for everyone else (the dashboard then hides the card).
    """
    actor = user["email"]
    hospitals = ctx.hospitals.list()
    models = [_model_card(ctx, modality) for modality in MODALITIES]
    counts = ctx.db.fetch_one(
        "SELECT COUNT(*) AS total, "
        "SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END) AS completed, "
        "SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) AS failed FROM fl_rounds"
    )
    active = ctx.db.fetch_all(
        "SELECT * FROM fl_rounds WHERE status NOT IN ('COMPLETED', 'FAILED') ORDER BY started_at DESC"
    )
    recent = ctx.db.fetch_all("SELECT * FROM fl_rounds ORDER BY started_at DESC LIMIT 5")

    def brief(row: Dict[str, Any]) -> Dict[str, Any]:
        metrics = row["global_metrics"] or {}
        return {
            "id": row["id"],
            "modality": row["modality"],
            "round_number": row["round_number"],
            "status": row["status"],
            "started_at": row["started_at"],
            "ended_at": row["ended_at"],
            "num_participants": row["num_participants"],
            "result_model_version": row["result_model_version"],
            "primary_metric": get_adapter(row["modality"]).task.primary_metric,
            "metrics": {k: metrics.get(k) for k in _METRIC_KEYS} if metrics else None,
            "error": row["error"],
        }

    try:
        surveillance: Dict[str, Any] = {"available": True, **ctx.surveillance.overview(actor)}
    except ServiceError as exc:
        surveillance = {"available": False, "reason": exc.message}

    forecast: Dict[str, Any] = {"available": False, "reason": "Surveillance data is not available."}
    if surveillance.get("available"):
        # Forecast the most unusual region, or the first disease's default region.
        target: Optional[tuple] = None
        for entry in surveillance["diseases"]:
            if entry["flagged_regions"]:
                top = entry["flagged_regions"][0]
                if target is None or (top["anomaly_score"] or 0) > target[2]:
                    target = (top["region_id"], entry["disease"]["id"], top["anomaly_score"] or 0)
        try:
            result = ctx.forecasts.forecast(target[0] if target else None, target[1] if target else None, 8, actor)
            forecast = {
                "available": result["available"],
                "reason": result.get("reason"),
                "region_id": result["region_id"],
                "region_name": result["region_name"],
                "disease": result["disease"],
                "model_name": result.get("model_name"),
                "horizon": result["forecast_horizon"],
                "last_observed": next(
                    (h["case_count"] for h in reversed(result["history"]) if h["case_count"] is not None), None
                ),
                "next_week": result["forecast"][0] if result["available"] else None,
                "final_week": result["forecast"][-1] if result["available"] else None,
                "evaluation_metrics": result.get("evaluation_metrics"),
                "disclaimer": result["disclaimer"],
            }
        except ServiceError as exc:
            forecast = {"available": False, "reason": exc.message}

    trained = [m for m in models if m.get("available") and m["metrics"]]
    simulated = ctx.settings.demo_mode or any(h["is_simulated"] for h in hospitals)
    return {
        "kpis": {
            "participating_hospitals": len(hospitals),
            "hospitals_online": sum(1 for h in hospitals if h["online"]),
            "modalities": len(MODALITIES),
            "fl_rounds_total": int(counts["total"] or 0),
            "fl_rounds_completed": int(counts["completed"] or 0),
            "fl_rounds_failed": int(counts["failed"] or 0),
            "models_trained": len(trained),
        },
        "models": models,
        "active_rounds": [brief(r) for r in active],
        "recent_rounds": [brief(r) for r in recent],
        "hospitals": [
            {
                "id": h["id"],
                "name": h["name"],
                "online": h["online"],
                "fl_participation": h["fl_participation"],
                "rounds_completed": h["rounds_completed"],
                "modalities": h["modalities"],
                "current_round": h["current_round"],
                "last_activity_at": h["last_activity_at"],
            }
            for h in hospitals
        ],
        "surveillance": surveillance,
        "forecast": forecast,
        "recent_activity": None
        if user.get("role") not in AUDIT_READER_ROLES
        else [
            {
                "id": e["id"],
                "timestamp": e["timestamp"],
                "actor": e["actor"],
                "action": e["action"],
                "status": e["status"],
                "round_id": e["round_id"],
                "hospital_id": e["hospital_id"],
            }
            for e in ctx.audit.recent(8)
        ],
        "data_status": {
            "simulated": simulated,
            "label": ctx.settings.simulated_label if simulated else "Configured data sources",
        },
    }
