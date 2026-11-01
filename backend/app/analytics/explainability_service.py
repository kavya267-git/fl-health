"""Explainability API logic.

Two scopes, kept clearly apart:

* **global** - what the model relies on overall. For EHR this is the pooled
  mean |SHAP| per feature that hospitals computed locally during the last
  round. No record leaves a hospital for it.
* **individual** - why the model produced one particular prediction. These are
  computed on a small set of *synthetic reference cases* held by the
  coordinator, never on a hospital's patient. In a deployment, individual
  explanations for real patients would be produced inside the hospital.

If an explanation cannot be produced the response says so and why; values are
never made up.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from analytics.explainability.service import (
    ExplanationUnavailable,
    explain_ecg_beat,
    explain_ehr_record,
    explain_xray_image,
)
from app.database import Database
from app.services.audit_service import AuditService
from app.services.model_registry import STATUS_INITIAL, ModelRegistry
from app.utils.errors import NotFoundError, ValidationFailed
from app.utils.time import utc_now_iso
from ml.common.types import MODALITIES
from ml.ecg.preprocess import ECG_SAMPLE_RATE_HZ
from ml.ehr.features import feature_metadata
from ml.registry import get_adapter
from ml.simulation.hospitals import generate_reference_cases

REFERENCE_NOTE = (
    "Individual explanations use synthetic reference cases generated for demonstration. "
    "They are not patient records and were not used for training or evaluation."
)

#: Part of the cache key for individual explanations. Raise it when an
#: explanation method changes so stored results for the same model version
#: are recomputed. 2: Grad-CAM moved to a block with at least a 7x7 map.
_EXPLANATION_REVISION = 2


class ExplainabilityService:
    def __init__(self, db: Database, registry: ModelRegistry, audit: AuditService, storage_path: Path, seed: int = 7):
        self.db = db
        self.registry = registry
        self.audit = audit
        self.directory = Path(storage_path) / "reference_cases"
        self.seed = seed

    # ====================================================== reference cases
    def bootstrap(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        for modality in MODALITIES:
            path = self.directory / f"{modality}.npz"
            if not path.exists():
                cases = generate_reference_cases(modality, self.seed)
                np.savez_compressed(path, **cases)

    def _load_cases(self, modality: str) -> Dict[str, np.ndarray]:
        path = self.directory / f"{modality}.npz"
        if not path.exists():
            self.bootstrap()
        with np.load(path, allow_pickle=False) as archive:
            return {key: np.array(archive[key]) for key in archive.files}

    def cases(self, modality: str) -> List[Dict[str, Any]]:
        data = self._load_cases(modality)
        class_names = get_adapter(modality).task.class_names
        return [
            {
                "case_id": f"{modality}-case-{index + 1}",
                "title": f"Reference case {index + 1}",
                "true_class": class_names[int(label)],
                "synthetic": True,
            }
            for index, label in enumerate(data["y"])
        ]

    # ============================================================== explain
    def explain(
        self, modality: str, scope: str = "individual", case_id: Optional[str] = None, actor: str = "system"
    ) -> Dict[str, Any]:
        if modality not in MODALITIES:
            raise NotFoundError(f"Unknown modality '{modality}'")
        if scope not in ("global", "individual"):
            raise ValidationFailed("scope must be 'global' or 'individual'")

        model = self.registry.latest(modality)
        adapter = get_adapter(modality)
        cases = self.cases(modality)
        response: Dict[str, Any] = {
            "modality": modality,
            "scope": scope,
            "available": False,
            "reason": None,
            "explanation": None,
            "model": None
            if model is None
            else {
                "version": model["version"],
                "architecture": model["architecture"],
                "backend": model["backend"],
                "trained": model["status"] != STATUS_INITIAL,
                "round_id": model["round_id"],
                "is_simulated": model["is_simulated"],
            },
            "task": adapter.task_dict(),
            "cases": cases,
            "reference_note": REFERENCE_NOTE,
        }
        if model is None or model["status"] == STATUS_INITIAL:
            response["reason"] = (
                "The global model for this modality has not been trained yet. "
                "Complete a federated round to see explanations."
            )
            return response

        if scope == "global":
            if modality != "ehr":
                response["reason"] = (
                    "Global feature importance is shown for structured (EHR) features only. "
                    "For signals and images an overall ranking of inputs is not meaningful - "
                    "use an individual explanation instead."
                )
                return response
            stored = self.db.fetch_one(
                "SELECT payload, model_version, generated_at FROM analytics_results "
                "WHERE kind = 'explainability_global' AND result_key = :key",
                {"key": modality},
            )
            if stored is None or stored["model_version"] != model["version"]:
                response["reason"] = "No hospital reported feature importance for the current model version."
                return response
            response.update(available=True, explanation={**stored["payload"], "generated_at": stored["generated_at"]})
            return response

        # ---- individual
        case_ids = [c["case_id"] for c in cases]
        case_id = case_id or case_ids[0]
        if case_id not in case_ids:
            raise NotFoundError(f"Unknown reference case '{case_id}'")
        index = case_ids.index(case_id)
        key = f"{modality}:v{model['version']}:{case_id}:r{_EXPLANATION_REVISION}"
        cached = self.db.fetch_one(
            "SELECT payload FROM analytics_results WHERE kind = 'explainability_individual' AND result_key = :key",
            {"key": key},
        )
        if cached:
            response.update(available=True, explanation=cached["payload"])
            return response

        data = self._load_cases(modality)
        weights = self.registry.load_weights(modality, model["version"])
        try:
            if modality == "ehr":
                explanation = explain_ehr_record(
                    adapter, weights, data["X"][index], data["background"], feature_metadata()
                )
            elif modality == "ecg":
                explanation = explain_ecg_beat(adapter, weights, data["X"][index], ECG_SAMPLE_RATE_HZ)
            else:
                explanation = explain_xray_image(adapter, weights, data["X"][index])
        except ExplanationUnavailable as exc:
            response["reason"] = str(exc)
            return response

        explanation.update(
            case_id=case_id,
            true_class=cases[index]["true_class"],
            model_version=model["version"],
            generated_at=utc_now_iso(),
        )
        self.db.execute(
            "INSERT INTO analytics_results (kind, result_key, payload, model_version, is_simulated, generated_at) "
            "VALUES ('explainability_individual', :key, :payload, :version, :simulated, :now) "
            "ON CONFLICT (kind, result_key) DO UPDATE SET payload = excluded.payload, generated_at = excluded.generated_at",
            {
                "key": key,
                "payload": explanation,
                "version": model["version"],
                "simulated": True,
                "now": explanation["generated_at"],
            },
        )
        self.audit.record(
            "ANALYTICS_GENERATED",
            actor,
            model_version=f"{modality} v{model['version']}",
            details={"kind": "individual explanation", "method": explanation["method"], "case_id": case_id},
        )
        response.update(available=True, explanation=explanation)
        return response
