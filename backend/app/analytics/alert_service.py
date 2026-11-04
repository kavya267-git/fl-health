"""Alerts: a region becoming a potential hotspot, and what a health officer found when they looked.

An alert is created when a region's status for a disease is "Potential hotspot" in a week and was not the
week before. The officer acknowledges it, then records an outcome: confirmed, not confirmed, or a reporting
artefact, with a note. Every step is written to the audit log.

``precision()`` turns recorded outcomes into hotspot precision (confirmed / all outcomes). Alerts created from
simulated data are flagged, so precision computed from them is labelled as coming from demo outcomes.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from analytics.hotspot.detector import CANDIDATE_HOTSPOT
from app.analytics.surveillance_service import SurveillanceService
from app.database import Database
from app.services.audit_service import AuditService
from app.services.permissions import ensure_region_scope
from app.utils.errors import ConflictError, NotFoundError, ValidationFailed
from app.utils.time import utc_now_iso

OUTCOMES = {
    "CONFIRMED": "Confirmed",
    "NOT_CONFIRMED": "Not confirmed",
    "REPORTING_ARTEFACT": "Reporting artefact",
}
STATES = ("OPEN", "ACKNOWLEDGED", "CLOSED")
MAX_NOTE = 1000


class AlertService:
    def __init__(self, db: Database, audit: AuditService, surveillance: SurveillanceService, lookback_weeks: int = 12):
        self.db = db
        self.audit = audit
        self.surveillance = surveillance
        self.lookback_weeks = lookback_weeks
        self._synced_version: Optional[str] = None

    # ------------------------------------------------------------- creating
    def sync(self) -> int:
        """Create alerts for regions that became potential hotspots in the last ``lookback_weeks`` weeks."""
        try:
            version = self.surveillance._data_version()
            diseases = self.surveillance.diseases()
        except Exception:  # noqa: BLE001 - no surveillance data, so nothing to alert on
            return 0
        if version == self._synced_version:
            return 0
        created = 0
        simulated = self.surveillance.is_simulated()
        for disease in diseases:
            weeks = self.surveillance.regional_series(disease["id"])["weeks"]
            recent = weeks[-(self.lookback_weeks + 1) :]
            previous: Optional[set] = None
            for week in recent:
                result = self.surveillance._hotspots_all(disease["id"], week, "system")
                flagged = {r["region_id"]: r for r in result["regions"] if r["status"] == CANDIDATE_HOTSPOT}
                if previous is not None:
                    for region_id, region in flagged.items():
                        if region_id in previous:
                            continue  # still a hotspot: the alert from the week it began stays the one alert
                        created += self._create(disease["id"], region, week, simulated)
                previous = set(flagged)
        self._synced_version = version
        return created

    def _create(self, disease: str, region: Dict[str, Any], week: str, simulated: bool) -> int:
        key = {"r": region["region_id"], "d": disease, "w": week}
        if self.db.fetch_one("SELECT id FROM alerts WHERE region_id = :r AND disease = :d AND week_start = :w", key):
            return 0
        row = self.db.insert(
            "alerts",
            {
                "region_id": region["region_id"],
                "disease": disease,
                "week_start": week,
                "state": "OPEN",
                "case_count": region["case_count"],
                "usual_level": region["baseline_mean"],
                "created_at": utc_now_iso(),
                "is_simulated": simulated,
            },
        )
        self.audit.record(
            "ALERT_CREATED",
            "system",
            details={"alert_id": row["id"], "region_id": region["region_id"], "disease": disease, "week_start": week},
        )
        return 1

    # ------------------------------------------------------------- reading
    def list(self, jurisdiction: Optional[List[str]] = None, state: Optional[str] = None) -> List[Dict[str, Any]]:
        self.sync()
        if state is not None and state not in STATES:
            raise ValidationFailed(f"state must be one of {', '.join(STATES)}")
        rows = self.db.fetch_all("SELECT * FROM alerts ORDER BY week_start DESC, id DESC")
        names = {r["region_id"]: r["name"] for r in self.surveillance.regions()}
        labels = {d["id"]: d["label"] for d in self.surveillance.diseases()}
        return [
            self._public(row, names, labels)
            for row in rows
            if (jurisdiction is None or row["region_id"] in jurisdiction) and (state is None or row["state"] == state)
        ]

    def _public(self, row: Dict[str, Any], names: Dict[str, str], labels: Dict[str, str]) -> Dict[str, Any]:
        return {
            **row,
            "region_name": names.get(row["region_id"], row["region_id"]),
            "disease_label": labels.get(row["disease"], row["disease"]),
            "week_label": SurveillanceService._period(row["week_start"])["label"],
            "outcome_label": OUTCOMES.get(row["outcome"]) if row["outcome"] else None,
        }

    def _get(self, alert_id: int, user: Dict[str, Any]) -> Dict[str, Any]:
        row = self.db.fetch_one("SELECT * FROM alerts WHERE id = :id", {"id": alert_id})
        if row is None:
            raise NotFoundError("No such alert.")
        ensure_region_scope(user, [row["region_id"]])
        return row

    # ------------------------------------------------------------- workflow
    def acknowledge(self, alert_id: int, user: Dict[str, Any]) -> Dict[str, Any]:
        row = self._get(alert_id, user)
        if row["state"] != "OPEN":
            raise ConflictError("This alert has already been acknowledged.")
        now = utc_now_iso()
        self.db.update(
            "alerts", {"state": "ACKNOWLEDGED", "acknowledged_by": user["email"], "acknowledged_at": now}, {"id": alert_id}
        )
        self.audit.record(
            "ALERT_ACKNOWLEDGED",
            user["email"],
            details={"alert_id": alert_id, "region_id": row["region_id"], "disease": row["disease"], "week_start": row["week_start"]},
        )
        return self._one(alert_id)

    def record_outcome(self, alert_id: int, user: Dict[str, Any], outcome: str, note: str) -> Dict[str, Any]:
        row = self._get(alert_id, user)
        if outcome not in OUTCOMES:
            raise ValidationFailed(f"outcome must be one of {', '.join(OUTCOMES)}")
        note = " ".join((note or "").split())
        if not note:
            raise ValidationFailed("Add a short note on how the outcome was established.")
        if len(note) > MAX_NOTE:
            raise ValidationFailed(f"The note can be at most {MAX_NOTE} characters.")
        if row["state"] == "OPEN":
            raise ConflictError("Acknowledge the alert before recording an outcome.")
        if row["state"] == "CLOSED":
            raise ConflictError("An outcome has already been recorded for this alert.")
        self.db.update(
            "alerts",
            {"state": "CLOSED", "outcome": outcome, "outcome_note": note, "outcome_by": user["email"], "outcome_at": utc_now_iso()},
            {"id": alert_id},
        )
        self.audit.record(
            "ALERT_OUTCOME_RECORDED",
            user["email"],
            details={"alert_id": alert_id, "region_id": row["region_id"], "disease": row["disease"], "outcome": outcome},
        )
        return self._one(alert_id)

    def _one(self, alert_id: int) -> Dict[str, Any]:
        row = self.db.fetch_one("SELECT * FROM alerts WHERE id = :id", {"id": alert_id})
        names = {r["region_id"]: r["name"] for r in self.surveillance.regions()}
        labels = {d["id"]: d["label"] for d in self.surveillance.diseases()}
        return self._public(row, names, labels)

    # ------------------------------------------------------------- evaluation
    def precision(self) -> Dict[str, Any]:
        """Hotspot precision from recorded outcomes, separately for simulated (demo) and real alerts."""
        rows = self.db.fetch_all("SELECT outcome, is_simulated FROM alerts WHERE state = 'CLOSED'")
        result = {}
        for simulated in (True, False):
            group = [r["outcome"] for r in rows if bool(r["is_simulated"]) == simulated]
            counts = {o: group.count(o) for o in OUTCOMES}
            judged = counts["CONFIRMED"] + counts["NOT_CONFIRMED"]
            result["demo" if simulated else "real"] = {
                "outcomes": len(group),
                **{o.lower(): n for o, n in counts.items()},
                # Artefacts are false alarms too; the second figure leaves them out to separate the two causes.
                "precision": counts["CONFIRMED"] / len(group) if group else None,
                "precision_excluding_artefacts": counts["CONFIRMED"] / judged if judged else None,
            }
        total_alerts = self.db.fetch_one("SELECT COUNT(*) AS n FROM alerts")["n"]
        return {**result, "alerts": total_alerts}
