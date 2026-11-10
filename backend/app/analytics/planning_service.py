"""Resource planning for a hospital manager: capacity, disease assumptions and the bed projection.

The arithmetic is in ``analytics/planning/projection.py`` (see its docstring and docs/resource-planning.md).
This service supplies its inputs: the hospital's latest capacity entry, the admin-set disease assumptions, the
hospital's share of each region's cases, and the stored ensemble forecast. Every step that cannot be computed
(no capacity entered, no forecast yet, a region without a forecast or a usable share) is reported, not filled.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from analytics.planning.projection import SHARE_WEEKS, DiseaseAssumptions, hospital_share, project
from app.analytics.ensemble_service import EnsembleService
from app.analytics.surveillance_service import SurveillanceService
from app.database import Database
from app.services.audit_service import AuditService
from app.utils.errors import NotFoundError, ValidationFailed
from app.utils.time import utc_now_iso

ASSUMED_LABEL = "Assumed values, replace with local figures"
PLANNING_LABEL = "Planning estimate"

#: Placeholder assumptions, clearly labelled as assumed until an administrator replaces them.
DEFAULT_ASSUMPTIONS = {
    "dengue": {"admission_rate": 0.20, "icu_share": 0.05, "length_of_stay_days": 4.0},
    "influenza_like_illness": {"admission_rate": 0.05, "icu_share": 0.10, "length_of_stay_days": 5.0},
    "acute_gastroenteritis": {"admission_rate": 0.10, "icu_share": 0.02, "length_of_stay_days": 3.0},
}
FALLBACK_ASSUMPTIONS = {"admission_rate": 0.10, "icu_share": 0.05, "length_of_stay_days": 4.0}


class PlanningService:
    def __init__(self, db: Database, audit: AuditService, surveillance: SurveillanceService, ensemble: EnsembleService):
        self.db = db
        self.audit = audit
        self.surveillance = surveillance
        self.ensemble = ensemble

    # --------------------------------------------------------------- assumptions
    def seed_assumptions(self) -> None:
        """Insert the labelled defaults for any disease without assumptions. Never overwrites admin values."""
        try:
            diseases = self.surveillance.diseases()
        except Exception:  # noqa: BLE001 - no surveillance data yet
            return
        for disease in diseases:
            if self.db.fetch_one("SELECT disease FROM disease_assumptions WHERE disease = :d", {"d": disease["id"]}):
                continue
            values = DEFAULT_ASSUMPTIONS.get(disease["id"], FALLBACK_ASSUMPTIONS)
            self.db.insert(
                "disease_assumptions",
                {"disease": disease["id"], **values, "is_default": True, "updated_by": "system", "updated_at": utc_now_iso()},
            )

    def assumptions(self) -> List[Dict[str, Any]]:
        labels = {d["id"]: d["label"] for d in self.surveillance.diseases()}
        rows = self.db.fetch_all("SELECT * FROM disease_assumptions ORDER BY disease")
        return [
            {
                **row,
                "is_default": bool(row["is_default"]),
                "disease_label": labels.get(row["disease"], row["disease"]),
                "label": ASSUMED_LABEL if row["is_default"] else "Set by an administrator",
            }
            for row in rows
            if row["disease"] in labels
        ]

    def set_assumptions(self, disease: str, values: Dict[str, float], actor: str) -> Dict[str, Any]:
        row = self.db.fetch_one("SELECT * FROM disease_assumptions WHERE disease = :d", {"d": disease})
        if row is None:
            raise NotFoundError(f"Unknown disease '{disease}'")
        admission, icu, stay = values["admission_rate"], values["icu_share"], values["length_of_stay_days"]
        if not (0 <= admission <= 1 and 0 <= icu <= 1):
            raise ValidationFailed("The admission rate and ICU share must be between 0 and 1.")
        if not 0 < stay <= 365:
            raise ValidationFailed("The length of stay must be between 0 and 365 days.")
        new = {"admission_rate": admission, "icu_share": icu, "length_of_stay_days": stay}
        self.db.update(
            "disease_assumptions", {**new, "is_default": False, "updated_by": actor, "updated_at": utc_now_iso()}, {"disease": disease}
        )
        self.audit.record(
            "PLANNING_ASSUMPTIONS_CHANGED",
            actor,
            details={"disease": disease, "from": {k: row[k] for k in new}, "to": new},
        )
        return next(a for a in self.assumptions() if a["disease"] == disease)

    # --------------------------------------------------------------- capacity
    def capacity(self, hospital_id: str) -> Optional[Dict[str, Any]]:
        return self.db.fetch_one(
            "SELECT * FROM hospital_capacity WHERE hospital_id = :h ORDER BY id DESC LIMIT 1", {"h": hospital_id}
        )

    def capacity_history(self, hospital_id: str) -> List[Dict[str, Any]]:
        return self.db.fetch_all("SELECT * FROM hospital_capacity WHERE hospital_id = :h ORDER BY id DESC", {"h": hospital_id})

    def set_capacity(self, hospital_id: str, total_beds: int, icu_beds: int, occupancy_percent: float, actor: str) -> Dict[str, Any]:
        if total_beds < 1 or total_beds > 100_000:
            raise ValidationFailed("Total beds must be between 1 and 100,000.")
        if icu_beds < 0 or icu_beds > total_beds:
            raise ValidationFailed("ICU beds must be between 0 and the total number of beds.")
        if not 0 <= occupancy_percent <= 100:
            raise ValidationFailed("Current occupancy must be between 0 and 100%.")
        previous = self.capacity(hospital_id)
        row = self.db.insert(
            "hospital_capacity",
            {
                "hospital_id": hospital_id,
                "total_beds": total_beds,
                "icu_beds": icu_beds,
                "occupancy_percent": occupancy_percent,
                "entered_by": actor,
                "entered_at": utc_now_iso(),
            },
        )
        keys = ("total_beds", "icu_beds", "occupancy_percent")
        self.audit.record(
            "HOSPITAL_CAPACITY_CHANGED",
            actor,
            hospital_id=hospital_id,
            details={"from": {k: previous[k] for k in keys} if previous else None, "to": {k: row[k] for k in keys}},
        )
        return row

    # --------------------------------------------------------------- projection
    def _hospital_series(self, hospital_id: str, disease: str, weeks: List[str]) -> Dict[str, List[Optional[float]]]:
        rows = self.db.fetch_all(
            "SELECT region_id, week_start, case_count, suppressed FROM surveillance_reports "
            "WHERE hospital_id = :h AND disease = :d",
            {"h": hospital_id, "d": disease},
        )
        position = {w: i for i, w in enumerate(weeks)}
        series: Dict[str, List[Optional[float]]] = {}
        for row in rows:
            values = series.setdefault(row["region_id"], [None] * len(weeks))
            index = position.get(str(row["week_start"]))
            if index is not None and not row["suppressed"] and row["case_count"] is not None:
                values[index] = float(row["case_count"])
        return series

    def projection(self, hospital_id: str) -> Dict[str, Any]:
        hospital = self.db.fetch_one("SELECT id, name FROM hospitals WHERE id = :h", {"h": hospital_id})
        if hospital is None:
            raise NotFoundError(f"No hospital '{hospital_id}'")
        self.surveillance._require_available()
        capacity = self.capacity(hospital_id)
        assumptions = {a["disease"]: a for a in self.assumptions()}
        run = self.ensemble.latest()
        base = {
            "hospital": hospital,
            "capacity": capacity,
            "assumptions": list(assumptions.values()),
            "label": PLANNING_LABEL,
            "data_status": self.surveillance.data_status(),
            "share_weeks": SHARE_WEEKS,
        }
        if capacity is None:
            return {**base, "available": False, "reason": "Enter your hospital's beds and current occupancy to see the projection."}
        if run is None:
            return {**base, "available": False, "reason": "The forecast is still being computed. The projection appears when it is ready."}

        current_beds = capacity["occupancy_percent"] / 100 * capacity["total_beds"]
        current_icu = capacity["occupancy_percent"] / 100 * capacity["icu_beds"]
        last = date.fromisoformat(run["data_through"])
        names = {r["region_id"]: r["name"] for r in self.surveillance.regions()}
        diseases, combined_beds = [], None
        for disease in self.surveillance.diseases():
            regional = self.surveillance.regional_series(disease["id"])
            mine = self._hospital_series(hospital_id, disease["id"], regional["weeks"])
            forecasts, shares, regions, missing = {}, {}, [], []
            for region_id in sorted(mine):
                name = names.get(region_id, region_id)
                share = hospital_share(mine[region_id], regional["counts"].get(region_id, []))
                points = run["forecasts"].get(f"{disease['id']}:{region_id}")
                if share is None:
                    missing.append({"region_id": region_id, "region_name": name, "reason": "no week in the last 8 with both counts known"})
                    continue
                if not points:
                    reason = run["excluded"].get(f"{disease['id']}:{region_id}", "no forecast")
                    missing.append({"region_id": region_id, "region_name": name, "share": share, "reason": reason})
                    continue
                shares[region_id] = share
                forecasts[region_id] = {
                    "low": [p["lower"] for p in points],
                    "mid": [p["predicted"] for p in points],
                    "high": [p["upper"] for p in points],
                }
                regions.append({"region_id": region_id, "region_name": name, "share": share})
            values = assumptions[disease["id"]]
            if not forecasts:
                diseases.append({"disease": disease, "available": False, "regions": regions, "missing_regions": missing, "assumptions": values})
                continue
            result = project(
                forecasts,
                shares,
                DiseaseAssumptions(values["admission_rate"], values["icu_share"], values["length_of_stay_days"]),
                current_beds,
            )
            weeks = self._weeks(result, last, capacity, current_icu)
            combined_beds = (
                [{k: w[k] for k in ("beds_low", "beds_mid", "beds_high")} for w in weeks]
                if combined_beds is None
                else [{k: c[k] + w[k] for k in c} for c, w in zip(combined_beds, weeks)]
            )
            diseases.append(
                {
                    "disease": disease,
                    "available": True,
                    "regions": regions,
                    "missing_regions": missing,
                    "assumptions": values,
                    "weeks": weeks,
                    "groups": group_weeks(weeks),
                }
            )
        combined = None
        if combined_beds is not None:
            combined = [
                {
                    "horizon": i + 1,
                    **c,
                    "total_low": current_beds + c["beds_low"],
                    "total_high": current_beds + c["beds_high"],
                    "over_capacity": current_beds + c["beds_high"] > capacity["total_beds"],
                }
                for i, c in enumerate(combined_beds)
            ]
        return {
            **base,
            "available": True,
            "current_beds_occupied": current_beds,
            "current_icu_occupied": current_icu,
            "forecast": {"data_through": run["data_through"], "computed_at": run["computed_at"], "level": run["level"]},
            "diseases": diseases,
            "all_diseases": combined,
        }

    @staticmethod
    def _weeks(result: Dict[str, List[float]], last: date, capacity: Dict[str, Any], current_icu: float) -> List[Dict[str, Any]]:
        weeks = []
        for i in range(len(result["beds_mid"])):
            start = last + timedelta(weeks=i + 1)
            weeks.append(
                {
                    "horizon": i + 1,
                    "week_start": start.isoformat(),
                    "label": SurveillanceService._period(start.isoformat())["label"],
                    **{key: values[i] for key, values in result.items()},
                    "over_capacity": result["total_beds_high"][i] > capacity["total_beds"],
                    "icu_total_high": current_icu + result["icu_beds_high"][i],
                    "icu_over_capacity": current_icu + result["icu_beds_high"][i] > capacity["icu_beds"],
                }
            )
        return weeks


def group_weeks(weeks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Consecutive weeks with the same over-capacity flag, with the range of beds they need."""
    groups: List[Dict[str, Any]] = []
    for week in weeks:
        if groups and groups[-1]["over_capacity"] == week["over_capacity"]:
            group = groups[-1]
            group["last_week"] = week["horizon"]
            group["total_low"] = min(group["total_low"], week["total_beds_low"])
            group["total_high"] = max(group["total_high"], week["total_beds_high"])
            group["beds_low"] = min(group["beds_low"], week["beds_low"])
            group["beds_high"] = max(group["beds_high"], week["beds_high"])
        else:
            groups.append(
                {
                    "first_week": week["horizon"],
                    "last_week": week["horizon"],
                    "over_capacity": week["over_capacity"],
                    "total_low": week["total_beds_low"],
                    "total_high": week["total_beds_high"],
                    "beds_low": week["beds_low"],
                    "beds_high": week["beds_high"],
                }
            )
    return groups
