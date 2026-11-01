"""Privacy report: configuration, validation checks and DP accounting."""

from __future__ import annotations

from typing import Any, Dict

from analytics.privacy import validation
from analytics.privacy.dp import ACCOUNTING_ASSUMPTIONS, account_rounds
from app.database import Database

PRIVACY_STATEMENT = (
    "Federated learning reduces the need to centralise raw patient data: hospitals train locally and share "
    "only model updates. It does not by itself guarantee privacy - model updates can still leak information "
    "about the data they were trained on."
)


class PrivacyService:
    def __init__(self, db: Database, settings):
        self.db = db
        self.settings = settings

    def report(self) -> Dict[str, Any]:
        settings = self.settings
        updates = self.db.fetch_all(
            "SELECT hospital_id, modality, round_id, status, dp_report, received_at FROM model_updates ORDER BY received_at"
        )
        accepted = [u for u in updates if u["status"] != "REJECTED"]
        counts = [row["case_count"] for row in self.db.fetch_all("SELECT case_count FROM surveillance_reports")]
        hospital_root = settings.hospital_data_root if settings.hospital_nodes == "in-process" else None
        checks = [
            validation.check_central_schema(self.db.table_columns()),
            validation.check_storage_separation(settings.model_storage_path, hospital_root),
            validation.check_update_payloads(updates),
            validation.check_small_cells(counts, settings.suppression_threshold),
            validation.check_differential_privacy([u["dp_report"] or {"enabled": False} for u in accepted]),
            validation.check_transport(settings.api_base_url, settings.demo_mode),
        ]

        accounting = []
        pairs = sorted({(u["hospital_id"], u["modality"]) for u in accepted})
        for hospital_id, modality in pairs:
            reports = [
                u["dp_report"] or {"enabled": False}
                for u in accepted
                if u["hospital_id"] == hospital_id and u["modality"] == modality
            ]
            entry = account_rounds(reports)
            entry.pop("assumptions")
            accounting.append({"hospital_id": hospital_id, "modality": modality, **entry})

        latest_round = self.db.fetch_one("SELECT id, config FROM fl_rounds ORDER BY started_at DESC LIMIT 1")
        return {
            "statement": PRIVACY_STATEMENT,
            "architecture": {
                "raw_data_location": "Raw data stays in each hospital node's own storage. The coordinator is never given a path to it.",
                "shared_with_coordinator": [
                    "Model weights after local training",
                    "Number of local training samples",
                    "Summary training and validation metrics",
                    "Confusion-matrix counts from local evaluation",
                    "Aggregate feature-importance values (EHR)",
                    "Weekly case counts per region and disease, with small counts suppressed",
                ],
                "never_shared": [
                    "Patient records",
                    "Images or signals",
                    "Patient-level locations",
                    "Individual predictions",
                ],
            },
            "differential_privacy": {
                "prototype": True,
                "mechanism": "Per-update L2 clipping followed by Gaussian noise, applied at the hospital node.",
                "configured_per_round": True,
                "latest_round": None
                if latest_round is None
                else {
                    "round_id": latest_round["id"],
                    **latest_round["config"]["differential_privacy"],
                },
                "accounting": accounting,
                "assumptions": ACCOUNTING_ASSUMPTIONS,
            },
            "small_cell_suppression": {"threshold": settings.suppression_threshold},
            "checks": checks,
            "overall_status": validation.overall_status(checks),
            "caveat": (
                "These checks inspect this running prototype. They are evidence that the workflow keeps "
                "raw data at the hospitals, not a proof of privacy and not a compliance assessment."
            ),
        }
