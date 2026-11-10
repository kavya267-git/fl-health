"""Federated-learning coordinator.

Owns the lifecycle of a round:

    CREATED -> WAITING_FOR_CLIENTS -> TRAINING -> UPDATES_RECEIVING
            -> AGGREGATING -> EVALUATING -> COMPLETED          (or FAILED)

The coordinator only ever handles model weights, sample counts and summary
metrics. It has no access to any hospital's data directory. Evaluation of the
aggregated model is federated too: each hospital scores the new global model
on its own held-out split and returns a confusion matrix, which is pooled here.
"""

from __future__ import annotations

import logging
import shutil
import threading
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from analytics.explainability.service import pool_global_importance
from analytics.privacy.dp import DPConfig
from app.database import Database
from app.federated.fedavg import ClientUpdate, aggregation_weights, federated_average
from app.federated.validation import UpdateRejected, validate_update
from app.services.audit_service import AuditService
from app.services.model_registry import ModelRegistry
from app.utils.errors import ConflictError, NotFoundError, PermissionDenied, ValidationFailed
from app.utils.time import utc_now, utc_now_iso
from ml.common.types import MODALITIES, EvalResult, TrainConfig
from ml.common.weights import weights_from_bytes, weights_to_bytes
from ml.ehr.features import feature_metadata
from ml.evaluation.metrics import metrics_from_evaluation, pool_evaluations
from ml.registry import get_adapter

# Round statuses
CREATED = "CREATED"
WAITING_FOR_CLIENTS = "WAITING_FOR_CLIENTS"
TRAINING = "TRAINING"
UPDATES_RECEIVING = "UPDATES_RECEIVING"
AGGREGATING = "AGGREGATING"
EVALUATING = "EVALUATING"
COMPLETED = "COMPLETED"
FAILED = "FAILED"
ROUND_STATUSES = (
    CREATED,
    WAITING_FOR_CLIENTS,
    TRAINING,
    UPDATES_RECEIVING,
    AGGREGATING,
    EVALUATING,
    COMPLETED,
    FAILED,
)
TERMINAL = (COMPLETED, FAILED)
COLLECTING = (WAITING_FOR_CLIENTS, TRAINING, UPDATES_RECEIVING)

# Participant statuses
P_INVITED = "INVITED"
P_JOINED = "JOINED"
P_TRAINING = "TRAINING"
P_SUBMITTED = "UPDATE_SUBMITTED"
P_REJECTED = "UPDATE_REJECTED"
P_EVALUATED = "EVALUATED"
P_EVALUATION_FAILED = "EVALUATION_FAILED"
P_DROPPED = "DROPPED"
P_FAILED = "FAILED"
P_PENDING = (P_INVITED, P_JOINED, P_TRAINING)

SYSTEM_ACTOR = "coordinator"

#: How long hospitals have to send an update (and, after aggregation, an
#: evaluation) before they are dropped from the round.
DEFAULT_DEADLINE_SECONDS = 600
MIN_DEADLINE_SECONDS = 10
MAX_DEADLINE_SECONDS = 24 * 3600

logger = logging.getLogger("fl.coordinator")


def _iso_after(seconds: float) -> str:
    return (utc_now() + timedelta(seconds=seconds)).isoformat(timespec="milliseconds")


def _is_past(moment: Optional[str], now: datetime) -> bool:
    return bool(moment) and now >= datetime.fromisoformat(moment)


class Coordinator:
    def __init__(
        self,
        db: Database,
        registry: ModelRegistry,
        audit: AuditService,
        storage_path: Path,
        max_update_bytes: int,
        default_seed: int = 0,
    ):
        self.db = db
        self.registry = registry
        self.audit = audit
        self.storage_path = Path(storage_path)
        self.max_update_bytes = max_update_bytes
        self.default_seed = default_seed
        self._locks: Dict[str, threading.RLock] = defaultdict(threading.RLock)
        self._locks_guard = threading.Lock()
        self._start_lock = threading.Lock()

    # ================================================================ helpers
    def _lock(self, round_id: str) -> threading.RLock:
        with self._locks_guard:
            return self._locks[round_id]

    def _round_dir(self, round_id: str) -> Path:
        return self.storage_path / "rounds" / round_id

    def _update_file(self, round_id: str, hospital_id: str) -> Path:
        return self._round_dir(round_id) / f"update_{hospital_id}.npz"

    def _aggregated_file(self, round_id: str) -> Path:
        return self._round_dir(round_id) / "aggregated.npz"

    def _cleanup(self, round_id: str) -> None:
        shutil.rmtree(self._round_dir(round_id), ignore_errors=True)
        self.db.execute(
            "UPDATE model_updates SET storage_path = NULL WHERE round_id = :round_id", {"round_id": round_id}
        )

    def _set_round(self, round_id: str, **values: Any) -> None:
        self.db.update("fl_rounds", values, {"id": round_id})

    def _set_participant(self, round_id: str, hospital_id: str, **values: Any) -> None:
        self.db.update("fl_participants", values, {"round_id": round_id, "hospital_id": hospital_id})

    def _touch_hospital(self, hospital_id: str) -> None:
        self.db.update("hospitals", {"last_activity_at": utc_now_iso()}, {"id": hospital_id})

    # ================================================================ queries
    def get_round(self, round_id: str) -> Dict[str, Any]:
        row = self.db.fetch_one("SELECT * FROM fl_rounds WHERE id = :id", {"id": round_id})
        if row is None:
            raise NotFoundError(f"Round '{round_id}' does not exist")
        return row

    def list_rounds(self, modality: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        if modality:
            return self.db.fetch_all(
                "SELECT * FROM fl_rounds WHERE modality = :modality ORDER BY started_at DESC LIMIT :limit",
                {"modality": modality, "limit": limit},
            )
        return self.db.fetch_all("SELECT * FROM fl_rounds ORDER BY started_at DESC LIMIT :limit", {"limit": limit})

    def participants(self, round_id: str) -> List[Dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT p.*, h.name AS hospital_name FROM fl_participants p JOIN hospitals h ON h.id = p.hospital_id "
            "WHERE p.round_id = :round_id ORDER BY p.hospital_id",
            {"round_id": round_id},
        )

    def _participant(self, round_id: str, hospital_id: str) -> Dict[str, Any]:
        row = self.db.fetch_one(
            "SELECT * FROM fl_participants WHERE round_id = :round_id AND hospital_id = :hospital_id",
            {"round_id": round_id, "hospital_id": hospital_id},
        )
        if row is None:
            raise PermissionDenied(f"Hospital '{hospital_id}' is not a participant in round '{round_id}'")
        return row

    def updates(self, round_id: str) -> List[Dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT * FROM model_updates WHERE round_id = :round_id ORDER BY received_at", {"round_id": round_id}
        )

    def active_round(self, modality: str) -> Optional[Dict[str, Any]]:
        return self.db.fetch_one(
            "SELECT * FROM fl_rounds WHERE modality = :modality AND status NOT IN ('COMPLETED', 'FAILED') "
            "ORDER BY started_at DESC LIMIT 1",
            {"modality": modality},
        )

    def pending_rounds_for(self, hospital_id: str) -> List[str]:
        """Open rounds a hospital has been invited to but has not joined yet."""
        rows = self.db.fetch_all(
            "SELECT r.id FROM fl_participants p JOIN fl_rounds r ON r.id = p.round_id "
            "WHERE p.hospital_id = :hospital_id AND p.status = 'INVITED' "
            "AND r.status IN ('WAITING_FOR_CLIENTS', 'TRAINING', 'UPDATES_RECEIVING') ORDER BY r.started_at",
            {"hospital_id": hospital_id},
        )
        return [row["id"] for row in rows]

    def round_metrics(self, round_id: str) -> Dict[str, Any]:
        round_row = self.get_round(round_id)
        rows = self.db.fetch_all(
            "SELECT * FROM training_metrics WHERE round_id = :round_id ORDER BY id", {"round_id": round_id}
        )
        return {
            "round_id": round_id,
            "modality": round_row["modality"],
            "status": round_row["status"],
            "global_metrics": round_row["global_metrics"],
            "local": [r for r in rows if r["scope"] == "local"],
            "global_per_hospital": [r for r in rows if r["scope"] == "global_per_hospital"],
        }

    # =============================================================== 1. start
    def start_round(
        self,
        modality: str,
        candidate_hospitals: List[Dict[str, Any]],
        actor: str,
        local_epochs: int = 2,
        batch_size: int = 32,
        learning_rate: float = 0.003,
        min_participants: int = 2,
        auto_aggregate: bool = True,
        dp: Optional[DPConfig] = None,
        is_simulated: bool = True,
        deadline_seconds: int = DEFAULT_DEADLINE_SECONDS,
        simulated_missing_rate: float = 0.0,
    ) -> Dict[str, Any]:
        """Create a round, select the participating hospitals and open it for clients.

        ``candidate_hospitals`` are hospital rows already filtered by the caller
        (requested ids, or all hospitals). Offline hospitals and hospitals
        without the modality are not selected.

        Hospitals that have not sent an update within ``deadline_seconds`` are
        dropped; the round then aggregates if at least ``min_participants``
        updates arrived, and fails otherwise. The same allowance applies to
        evaluation after aggregation.
        """
        if not MIN_DEADLINE_SECONDS <= deadline_seconds <= MAX_DEADLINE_SECONDS:
            raise ValidationFailed(
                f"deadline_seconds must be between {MIN_DEADLINE_SECONDS} and {MAX_DEADLINE_SECONDS}"
            )
        if modality not in MODALITIES:
            raise ValidationFailed(f"Unknown modality '{modality}'. Expected one of {list(MODALITIES)}")
        train_config = TrainConfig(local_epochs, batch_size, learning_rate, self.default_seed)
        try:
            train_config.validate()
            dp = dp or DPConfig()
            dp.validate()
        except ValueError as exc:
            raise ValidationFailed(str(exc)) from exc
        if min_participants < 1:
            raise ValidationFailed("min_participants must be at least 1")
        if not 0.0 <= simulated_missing_rate <= 0.5:
            raise ValidationFailed("simulated_missing_rate must be between 0 and 0.5")
        if simulated_missing_rate > 0 and modality != "ehr":
            raise ValidationFailed("Simulated missing values apply to EHR rounds only")

        selected = [
            h
            for h in candidate_hospitals
            if h["online"] and h.get("participating", True) and modality in (h["modalities"] or [])
        ]
        if len(selected) < min_participants:
            opted_out = sum(1 for h in candidate_hospitals if not h.get("participating", True))
            raise ConflictError(
                f"Only {len(selected)} online hospital(s) can take part in a {modality.upper()} round; "
                f"{min_participants} are required."
                + (f" {opted_out} hospital(s) have switched participation off." if opted_out else "")
            )

        with self._start_lock:
            if self.active_round(modality) is not None:
                raise ConflictError(
                    f"A {modality.upper()} round is already in progress. Wait for it to finish before starting another."
                )
            model = self.registry.ensure_initial(modality, is_simulated)
            adapter = get_adapter(modality)
            previous = self.db.fetch_one(
                "SELECT MAX(round_number) AS n FROM fl_rounds WHERE modality = :modality", {"modality": modality}
            )
            round_number = int(previous["n"] or 0) + 1
            round_id = f"{modality}-r{round_number:04d}"
            config = {
                "training": {
                    "local_epochs": local_epochs,
                    "batch_size": batch_size,
                    "learning_rate": learning_rate,
                    "seed": self.default_seed + round_number,
                    **(
                        {"missingness": {"mcar_rate": simulated_missing_rate, "seed": self.default_seed}}
                        if simulated_missing_rate > 0
                        else {}
                    ),
                },
                "differential_privacy": dp.to_dict(),
                "min_participants": min_participants,
                "auto_aggregate": auto_aggregate,
                "deadline": {
                    "seconds": deadline_seconds,
                    "training_deadline_at": _iso_after(deadline_seconds),
                    "evaluation_deadline_at": None,
                },
                "model": {
                    "architecture": model["architecture"],
                    "backend": model["backend"],
                    "architecture_signature": model["architecture_signature"],
                    "signature_label": adapter.signature_label,
                    "base_version": model["version"],
                },
                "explainability": {"global_importance": modality == "ehr"},
            }
            now = utc_now_iso()
            self.db.insert(
                "fl_rounds",
                {
                    "id": round_id,
                    "round_number": round_number,
                    "modality": modality,
                    "status": CREATED,
                    "config": config,
                    "base_model_version": model["version"],
                    "result_model_version": None,
                    "num_participants": len(selected),
                    "aggregation_status": "PENDING",
                    "global_metrics": None,
                    "error": None,
                    "created_by": actor,
                    "is_simulated": is_simulated,
                    "started_at": now,
                    "ended_at": None,
                },
            )
            for hospital in selected:
                self.db.insert(
                    "fl_participants",
                    {
                        "id": f"{round_id}:{hospital['id']}",
                        "round_id": round_id,
                        "hospital_id": hospital["id"],
                        "status": P_INVITED,
                    },
                )
            self.audit.record(
                "FL_ROUND_CREATED",
                actor,
                round_id=round_id,
                model_version=f"{modality} v{model['version']}",
                details={"modality": modality, "hospitals": [h["id"] for h in selected], "config": config},
            )
            self._set_round(round_id, status=WAITING_FOR_CLIENTS)
        return self.get_round(round_id)

    # ================================================================ 2. join
    def node_round_info(self, round_id: str) -> Dict[str, Any]:
        round_row = self.get_round(round_id)
        config = round_row["config"]
        return {
            "round_id": round_id,
            "modality": round_row["modality"],
            "status": round_row["status"],
            "training": config["training"],
            "differential_privacy": config["differential_privacy"],
            "model": config["model"],
            "explainability": config.get("explainability", {}),
        }

    def join(self, round_id: str, hospital_id: str, data_summary: Optional[dict] = None) -> Dict[str, Any]:
        with self._lock(round_id):
            round_row = self.get_round(round_id)
            if round_row["status"] not in COLLECTING:
                raise ConflictError(f"Round '{round_id}' is {round_row['status']} and no longer accepts participants")
            participant = self._participant(round_id, hospital_id)
            if participant["status"] != P_INVITED:
                raise ConflictError(f"Hospital '{hospital_id}' has already joined round '{round_id}'")
            self._set_participant(round_id, hospital_id, status=P_JOINED, joined_at=utc_now_iso())
            if data_summary:
                self.db.update(
                    "hospitals", {"data_summary": data_summary, "last_activity_at": utc_now_iso()}, {"id": hospital_id}
                )
            else:
                self._touch_hospital(hospital_id)
            self.audit.record("HOSPITAL_JOINED_ROUND", hospital_id, hospital_id=hospital_id, round_id=round_id)
        return self.node_round_info(round_id)

    # ==================================================== 3-4. distribute model
    def global_model_bytes(self, round_id: str, hospital_id: str, which: str = "base") -> bytes:
        """Weights a participant may download: the round's base model, or the aggregated result."""
        with self._lock(round_id):
            round_row = self.get_round(round_id)
            participant = self._participant(round_id, hospital_id)
            modality = round_row["modality"]
            if which == "base":
                if round_row["status"] not in COLLECTING:
                    raise ConflictError(
                        f"Round '{round_id}' is {round_row['status']}; the base model is no longer served"
                    )
                if participant["status"] not in (P_JOINED, P_TRAINING):
                    raise ConflictError(f"Hospital '{hospital_id}' must join the round before downloading the model")
                payload = self.registry.load_bytes(modality, round_row["base_model_version"])
                self._set_participant(round_id, hospital_id, status=P_TRAINING)
                if round_row["status"] == WAITING_FOR_CLIENTS:
                    self._set_round(round_id, status=TRAINING)
                version_label = f"{modality} v{round_row['base_model_version']}"
            elif which == "result":
                if round_row["status"] != EVALUATING:
                    raise ConflictError(f"Round '{round_id}' is {round_row['status']}; no aggregated model to evaluate")
                payload = self._aggregated_file(round_id).read_bytes()
                version_label = f"{modality} round {round_row['round_number']} aggregate"
            else:
                raise ValidationFailed("'which' must be 'base' or 'result'")
            self._touch_hospital(hospital_id)
            self.audit.record(
                "MODEL_ACCESSED",
                hospital_id,
                hospital_id=hospital_id,
                round_id=round_id,
                model_version=version_label,
                details={"purpose": "local training" if which == "base" else "evaluation"},
            )
            return payload

    # =================================================== 5-8. receive + validate
    def receive_update(
        self,
        round_id: str,
        hospital_id: str,
        payload: bytes,
        num_samples: int,
        metrics: Optional[dict] = None,
        dp_report: Optional[dict] = None,
        declared_signature: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock(round_id):
            round_row = self.get_round(round_id)
            if round_row["status"] not in COLLECTING:
                raise ConflictError(f"Round '{round_id}' is {round_row['status']} and no longer accepts updates")
            participant = self._participant(round_id, hospital_id)
            if participant["status"] not in (P_JOINED, P_TRAINING):
                raise ConflictError(
                    f"Hospital '{hospital_id}' cannot submit an update in state {participant['status']}"
                )
            modality = round_row["modality"]
            model_config = round_row["config"]["model"]
            now = utc_now_iso()
            update_id = f"{round_id}:{hospital_id}"
            base_weights = self.registry.load_weights(modality, round_row["base_model_version"])

            try:
                validated = validate_update(
                    payload,
                    int(num_samples),
                    base_weights,
                    model_config["architecture_signature"],
                    model_config["signature_label"],
                    declared_signature,
                    self.max_update_bytes,
                )
            except UpdateRejected as exc:
                self.db.insert(
                    "model_updates",
                    {
                        "id": update_id,
                        "round_id": round_id,
                        "hospital_id": hospital_id,
                        "modality": modality,
                        "architecture_signature": declared_signature,
                        "num_samples": int(num_samples),
                        "size_bytes": len(payload),
                        "dp_report": dp_report,
                        "status": "REJECTED",
                        "rejection_reason": exc.reason,
                        "received_at": now,
                    },
                )
                self._set_participant(
                    round_id, hospital_id, status=P_REJECTED, error=exc.reason, update_received_at=now
                )
                self.audit.record(
                    "LOCAL_UPDATE_RECEIVED",
                    hospital_id,
                    status="REJECTED",
                    hospital_id=hospital_id,
                    round_id=round_id,
                    details={"reason": exc.reason},
                )
                self._after_participant_change(round_id)
                raise ValidationFailed(f"Update rejected: {exc.reason}") from exc

            path = self._update_file(round_id, hospital_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            self.db.insert(
                "model_updates",
                {
                    "id": update_id,
                    "round_id": round_id,
                    "hospital_id": hospital_id,
                    "modality": modality,
                    "architecture_signature": validated.signature,
                    "num_samples": int(num_samples),
                    "weights_sha256": validated.sha256,
                    "size_bytes": validated.size_bytes,
                    "update_norm": validated.update_norm,
                    "dp_report": dp_report,
                    "status": "VALIDATED",
                    "rejection_reason": None,
                    "storage_path": str(path),
                    "received_at": now,
                },
            )
            metrics = metrics or {}
            self._set_participant(
                round_id,
                hospital_id,
                status=P_SUBMITTED,
                num_samples=int(num_samples),
                local_metrics=metrics,
                update_received_at=now,
            )
            history = metrics.get("training_history") or []
            if history:
                self.db.insert(
                    "training_metrics",
                    {
                        "round_id": round_id,
                        "modality": modality,
                        "model_version": round_row["base_model_version"],
                        "scope": "local",
                        "hospital_id": hospital_id,
                        "split": "train",
                        "metrics": {"history": history, **history[-1]},
                        "num_samples": int(num_samples),
                        "created_at": now,
                    },
                )
            if metrics.get("local_validation"):
                self.db.insert(
                    "training_metrics",
                    {
                        "round_id": round_id,
                        "modality": modality,
                        "model_version": round_row["base_model_version"],
                        "scope": "local",
                        "hospital_id": hospital_id,
                        "split": "val",
                        "metrics": metrics["local_validation"],
                        "num_samples": metrics["local_validation"].get("num_samples"),
                        "created_at": now,
                    },
                )
            self._touch_hospital(hospital_id)
            self.audit.record(
                "LOCAL_UPDATE_RECEIVED",
                hospital_id,
                hospital_id=hospital_id,
                round_id=round_id,
                model_version=f"{modality} v{round_row['base_model_version']}",
                details={
                    "num_samples": int(num_samples),
                    "weights_sha256": validated.sha256,
                    "size_bytes": validated.size_bytes,
                    "update_norm": validated.update_norm,
                    "differential_privacy": bool((dp_report or {}).get("enabled")),
                },
            )
            self._set_round(round_id, status=UPDATES_RECEIVING)
            self._after_participant_change(round_id)
        return {
            "round_id": round_id,
            "hospital_id": hospital_id,
            "status": "VALIDATED",
            "weights_sha256": validated.sha256,
            "update_norm": validated.update_norm,
        }

    def _after_participant_change(self, round_id: str) -> None:
        """Decide whether the round can aggregate, must fail, or should keep waiting."""
        round_row = self.get_round(round_id)
        if round_row["status"] not in COLLECTING:
            return
        participants = self.participants(round_id)
        pending = [p for p in participants if p["status"] in P_PENDING]
        submitted = [p for p in participants if p["status"] == P_SUBMITTED]
        minimum = int(round_row["config"]["min_participants"])
        if len(submitted) + len(pending) < minimum:
            self.fail_round(
                round_id,
                f"Only {len(submitted)} valid update(s) can be collected; {minimum} are required for aggregation.",
            )
        elif not pending and round_row["config"].get("auto_aggregate", True):
            self.aggregate(round_id, SYSTEM_ACTOR)

    # ============================================================ 9-10. FedAvg
    def aggregate(self, round_id: str, actor: str) -> Dict[str, Any]:
        with self._lock(round_id):
            round_row = self.get_round(round_id)
            if round_row["status"] not in COLLECTING:
                raise ConflictError(f"Round '{round_id}' is {round_row['status']}; it cannot be aggregated now")
            modality = round_row["modality"]
            valid = [u for u in self.updates(round_id) if u["status"] == "VALIDATED"]
            minimum = int(round_row["config"]["min_participants"])
            if len(valid) < minimum:
                raise ConflictError(
                    f"{len(valid)} valid update(s) received; {minimum} are required before aggregation."
                )
            for participant in self.participants(round_id):
                if participant["status"] in P_PENDING:
                    self._set_participant(
                        round_id,
                        participant["hospital_id"],
                        status=P_DROPPED,
                        error="No update received before aggregation started.",
                    )
            self._set_round(round_id, status=AGGREGATING, aggregation_status="IN_PROGRESS")
            self.audit.record(
                "AGGREGATION_STARTED",
                actor,
                round_id=round_id,
                details={"algorithm": "FedAvg", "hospitals": [u["hospital_id"] for u in valid]},
            )
            try:
                client_updates = [
                    ClientUpdate(
                        u["hospital_id"], weights_from_bytes(Path(u["storage_path"]).read_bytes()), u["num_samples"]
                    )
                    for u in valid
                ]
                averaged = federated_average(client_updates)
                coefficients = aggregation_weights(client_updates)
                self._aggregated_file(round_id).write_bytes(weights_to_bytes(averaged))
            except Exception as exc:
                self._set_round(round_id, aggregation_status="FAILED")
                self.audit.record(
                    "AGGREGATION_COMPLETED", actor, status="FAILED", round_id=round_id, details={"error": str(exc)}
                )
                self.fail_round(round_id, f"Aggregation failed: {exc}")
                raise ConflictError(f"Aggregation failed: {exc}") from exc

            self.db.execute(
                "UPDATE model_updates SET status = 'AGGREGATED' WHERE round_id = :round_id AND status = 'VALIDATED'",
                {"round_id": round_id},
            )
            config = dict(round_row["config"])
            config["aggregation"] = {
                "algorithm": "FedAvg",
                "coefficients": coefficients,
                "total_samples": int(sum(u.num_samples for u in client_updates)),
            }
            if config.get("deadline"):
                config["deadline"] = {
                    **config["deadline"],
                    "evaluation_deadline_at": _iso_after(config["deadline"]["seconds"]),
                }
            self._set_round(round_id, status=EVALUATING, aggregation_status="COMPLETED", config=config)
            self.audit.record(
                "AGGREGATION_COMPLETED",
                actor,
                round_id=round_id,
                details={"algorithm": "FedAvg", "coefficients": coefficients, "modality": modality},
            )
        return self.get_round(round_id)

    # ========================================================== 11. evaluation
    def receive_evaluation(
        self, round_id: str, hospital_id: str, evaluation: dict, explanation: Optional[dict] = None
    ) -> Dict[str, Any]:
        with self._lock(round_id):
            round_row = self.get_round(round_id)
            if round_row["status"] != EVALUATING:
                raise ConflictError(f"Round '{round_id}' is {round_row['status']}; it is not being evaluated")
            participant = self._participant(round_id, hospital_id)
            if participant["status"] != P_SUBMITTED:
                raise ConflictError(
                    f"Hospital '{hospital_id}' cannot report an evaluation in state {participant['status']}"
                )
            adapter = get_adapter(round_row["modality"])
            try:
                result = EvalResult.from_dict(evaluation)
            except (KeyError, TypeError, ValueError) as exc:
                raise ValidationFailed(f"Malformed evaluation report: {exc}") from exc
            classes = adapter.task.num_classes
            if result.confusion.shape != (classes, classes) or (result.confusion < 0).any():
                raise ValidationFailed(f"The confusion matrix must be {classes}x{classes} with non-negative counts")
            if int(result.confusion.sum()) != result.num_samples or result.num_samples <= 0:
                raise ValidationFailed("num_samples must equal the sum of the confusion matrix and be positive")

            self._set_participant(
                round_id,
                hospital_id,
                status=P_EVALUATED,
                evaluated_at=utc_now_iso(),
                evaluation={"evaluation": result.to_dict(), "explanation": explanation},
            )
            self._touch_hospital(hospital_id)
            remaining = [p for p in self.participants(round_id) if p["status"] == P_SUBMITTED]
            if not remaining:
                self.finalize(round_id, SYSTEM_ACTOR)
        return {"round_id": round_id, "hospital_id": hospital_id, "status": "RECORDED"}

    # ================================================= 12-15. register + finish
    def finalize(self, round_id: str, actor: str, allow_partial: bool = False) -> Dict[str, Any]:
        """Pool evaluations, register the new global model and complete the round."""
        with self._lock(round_id):
            round_row = self.get_round(round_id)
            if round_row["status"] != EVALUATING:
                raise ConflictError(
                    f"Round '{round_id}' is {round_row['status']}; only an evaluating round can be finalised"
                )
            participants = self.participants(round_id)
            evaluated = [p for p in participants if p["status"] == P_EVALUATED]
            waiting = [p for p in participants if p["status"] == P_SUBMITTED]
            if not evaluated:
                raise ConflictError("No hospital has reported an evaluation of the aggregated model yet")
            if waiting and not allow_partial:
                raise ConflictError(
                    f"{len(waiting)} hospital(s) have not reported an evaluation yet. "
                    "Finalise with allow_partial to proceed without them."
                )

            modality = round_row["modality"]
            adapter = get_adapter(modality)
            now = utc_now_iso()
            results = [EvalResult.from_dict(p["evaluation"]["evaluation"]) for p in evaluated]
            metrics = metrics_from_evaluation(pool_evaluations(results), adapter.task)
            metrics["evaluated_hospitals"] = [p["hospital_id"] for p in evaluated]

            hospitals = {h["id"]: h for h in self.db.fetch_all("SELECT id, data_summary, is_simulated FROM hospitals")}
            trained = [p for p in participants if p["status"] in (P_SUBMITTED, P_EVALUATED, P_EVALUATION_FAILED)]
            sources = sorted(
                {
                    ((hospitals[p["hospital_id"]]["data_summary"] or {}).get(modality) or {}).get("source", "unknown")
                    for p in trained
                }
            )
            is_simulated = sources == ["simulated"]
            dataset = {
                "sources": sources,
                "simulated": is_simulated,
                "train_samples": int(sum(p["num_samples"] or 0 for p in trained)),
                "evaluation_samples": int(metrics["num_samples"]),
                "evaluation_split": (
                    "Each hospital's local held-out validation split, scored locally; "
                    "confusion matrices pooled across hospitals."
                ),
                "training_hospitals": [p["hospital_id"] for p in trained],
            }

            weights = weights_from_bytes(self._aggregated_file(round_id).read_bytes())
            model = self.registry.register_version(modality, weights, round_id, metrics, dataset, is_simulated)
            version_label = f"{modality} v{model['version']}"
            self.audit.record(
                "GLOBAL_MODEL_CREATED",
                actor,
                round_id=round_id,
                model_version=version_label,
                details={
                    "weights_sha256": model["weights_sha256"],
                    "architecture": model["architecture"],
                    "backend": model["backend"],
                },
            )

            self.db.insert(
                "training_metrics",
                {
                    "round_id": round_id,
                    "modality": modality,
                    "model_version": model["version"],
                    "scope": "global",
                    "hospital_id": None,
                    "split": "val",
                    "metrics": metrics,
                    "num_samples": int(metrics["num_samples"]),
                    "created_at": now,
                },
            )
            for participant, result in zip(evaluated, results):
                self.db.insert(
                    "training_metrics",
                    {
                        "round_id": round_id,
                        "modality": modality,
                        "model_version": model["version"],
                        "scope": "global_per_hospital",
                        "hospital_id": participant["hospital_id"],
                        "split": "val",
                        "metrics": metrics_from_evaluation(result, adapter.task),
                        "num_samples": result.num_samples,
                        "created_at": now,
                    },
                )

            explanation = (
                pool_global_importance([p["evaluation"].get("explanation") for p in evaluated], feature_metadata())
                if modality == "ehr"
                else None
            )
            if explanation is not None:
                explanation["model_version"] = model["version"]
                explanation["round_id"] = round_id
                self.db.execute(
                    "INSERT INTO analytics_results (kind, result_key, payload, model_version, is_simulated, generated_at) "
                    "VALUES ('explainability_global', :key, :payload, :version, :simulated, :now) "
                    "ON CONFLICT (kind, result_key) DO UPDATE SET payload = excluded.payload, "
                    "model_version = excluded.model_version, is_simulated = excluded.is_simulated, "
                    "generated_at = excluded.generated_at",
                    {
                        "key": modality,
                        "payload": explanation,
                        "version": model["version"],
                        "simulated": is_simulated,
                        "now": now,
                    },
                )
                self.audit.record(
                    "ANALYTICS_GENERATED",
                    actor,
                    round_id=round_id,
                    model_version=version_label,
                    details={"kind": "global feature importance", "hospitals": len(evaluated)},
                )

            self._set_round(
                round_id,
                status=COMPLETED,
                result_model_version=model["version"],
                global_metrics=metrics,
                ended_at=now,
                is_simulated=is_simulated,
            )
            self.audit.record(
                "FL_ROUND_COMPLETED",
                actor,
                round_id=round_id,
                model_version=version_label,
                details={k: metrics[k] for k in ("accuracy", "precision", "recall", "f1", "loss", "num_samples")},
            )
            self._cleanup(round_id)
        return self.get_round(round_id)

    # =============================================================== deadline
    def enforce_deadlines(self, now: Optional[datetime] = None) -> List[str]:
        """Drop hospitals that missed a round's deadline, then carry on with the rest.

        Called periodically by the server. Returns the ids of rounds it acted on.
        """
        now = now or utc_now()
        rows = self.db.fetch_all(
            "SELECT id FROM fl_rounds WHERE status IN "
            "('WAITING_FOR_CLIENTS', 'TRAINING', 'UPDATES_RECEIVING', 'EVALUATING')"
        )
        acted = []
        for row in rows:
            try:
                if self._enforce_deadline(row["id"], now):
                    acted.append(row["id"])
            except Exception:  # one bad round must not stop the others being checked
                logger.exception("Deadline check failed for round %s", row["id"])
        return acted

    def _drop(self, round_id: str, hospital_id: str, status: str, reason: str) -> None:
        self._set_participant(round_id, hospital_id, status=status, error=reason)
        self.audit.record(
            "HOSPITAL_DROPPED", SYSTEM_ACTOR, hospital_id=hospital_id, round_id=round_id, details={"reason": reason}
        )

    def _enforce_deadline(self, round_id: str, now: datetime) -> bool:
        with self._lock(round_id):
            round_row = self.get_round(round_id)
            deadline = round_row["config"].get("deadline") or {}
            seconds = deadline.get("seconds")
            minimum = int(round_row["config"]["min_participants"])
            participants = self.participants(round_id)

            if round_row["status"] in COLLECTING:
                if not _is_past(deadline.get("training_deadline_at"), now):
                    return False
                for p in participants:
                    if p["status"] in P_PENDING:
                        self._drop(
                            round_id,
                            p["hospital_id"],
                            P_DROPPED,
                            f"Missed the {seconds}s deadline: no update arrived in time.",
                        )
                submitted = [p for p in participants if p["status"] == P_SUBMITTED]
                if len(submitted) >= minimum:
                    self.aggregate(round_id, SYSTEM_ACTOR)
                else:
                    self.fail_round(
                        round_id,
                        f"The {seconds}s deadline passed with {len(submitted)} valid update(s); "
                        f"{minimum} are required for aggregation.",
                    )
                return True

            if round_row["status"] == EVALUATING:
                if not _is_past(deadline.get("evaluation_deadline_at"), now):
                    return False
                for p in participants:
                    if p["status"] == P_SUBMITTED:
                        # Its update is already in the model, so it stays a contributor;
                        # only its evaluation is missing.
                        self._drop(
                            round_id,
                            p["hospital_id"],
                            P_EVALUATION_FAILED,
                            f"Missed the {seconds}s deadline: no evaluation arrived in time.",
                        )
                if any(p["status"] == P_EVALUATED for p in participants):
                    self.finalize(round_id, SYSTEM_ACTOR, allow_partial=True)
                else:
                    self.fail_round(round_id, "No hospital evaluated the aggregated model before the deadline.")
                return True
        return False

    # ================================================================ failure
    def report_failure(self, round_id: str, hospital_id: str, stage: str, message: str) -> None:
        with self._lock(round_id):
            round_row = self.get_round(round_id)
            if round_row["status"] in TERMINAL:
                return
            participant = self._participant(round_id, hospital_id)
            message = f"{stage}: {message}"[:500]
            if round_row["status"] == EVALUATING:
                if participant["status"] != P_SUBMITTED:
                    return
                self._set_participant(round_id, hospital_id, status=P_EVALUATION_FAILED, error=message)
                participants = self.participants(round_id)
                if not [p for p in participants if p["status"] == P_SUBMITTED]:
                    if [p for p in participants if p["status"] == P_EVALUATED]:
                        self.finalize(round_id, SYSTEM_ACTOR)
                    else:
                        self.fail_round(round_id, "No hospital could evaluate the aggregated model.")
                return
            if participant["status"] in P_PENDING:
                self._set_participant(round_id, hospital_id, status=P_FAILED, error=message)
                if stage == "declined":
                    self.audit.record(
                        "HOSPITAL_DECLINED_ROUND", hospital_id, hospital_id=hospital_id, round_id=round_id,
                        details={"reason": message},
                    )
                self._after_participant_change(round_id)

    def fail_round(self, round_id: str, error: str, actor: str = SYSTEM_ACTOR) -> Dict[str, Any]:
        with self._lock(round_id):
            round_row = self.get_round(round_id)
            if round_row["status"] in TERMINAL:
                return round_row
            self._set_round(round_id, status=FAILED, error=error[:1000], ended_at=utc_now_iso())
            self.audit.record(
                "FL_ROUND_FAILED", actor, status="FAILED", round_id=round_id, details={"error": error[:1000]}
            )
            self._cleanup(round_id)
        return self.get_round(round_id)

    def recover_interrupted(self, reason: str) -> int:
        """Fail rounds left unfinished by a previous process (in-process nodes cannot resume)."""
        rows = self.db.fetch_all("SELECT id FROM fl_rounds WHERE status NOT IN ('COMPLETED', 'FAILED')")
        for row in rows:
            self.fail_round(row["id"], reason)
        return len(rows)
