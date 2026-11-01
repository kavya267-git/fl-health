"""Disease-surveillance API logic: regions, aggregated counts, hotspot candidates."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from analytics.geospatial import regions as region_tools
from analytics.geospatial.surveillance import (
    DISEASES,
    ReportValidationError,
    aggregate_regional,
    case_rate_per_100k,
    iso_week_label,
    last_complete_week,
    simulate_reports,
    validate_reports,
)
from analytics.hotspot.detector import (
    CANDIDATE_HOTSPOT,
    ELEVATED,
    INSUFFICIENT_DATA,
    NORMAL,
    STATUS_LABELS,
    HotspotParams,
    detect_hotspots,
)
from app.database import Database
from app.services.audit_service import AuditService
from app.utils.errors import NotFoundError, UnavailableError, ValidationFailed
from app.utils.time import utc_now_iso

HOTSPOT_DISCLAIMER = (
    "A potential hotspot is a statistical signal that a region's weekly count is unusually high "
    "compared with its own recent weeks. It is a candidate for further investigation, "
    "not a confirmed outbreak."
)


class SurveillanceService:
    def __init__(self, db: Database, audit: AuditService, settings):
        self.db = db
        self.audit = audit
        self.settings = settings
        self.params = HotspotParams()
        self._unavailable_reason: Optional[str] = None
        self._series_cache: Dict[str, Tuple[str, Any]] = {}

    # ============================================================ bootstrap
    def bootstrap(self, hospital_ids: List[str]) -> None:
        """Load regions and hospital reports (simulated in demo mode, from files otherwise)."""
        settings = self.settings
        try:
            if settings.regions_geojson_path:
                collection = region_tools.load_regions(
                    settings.regions_geojson_path,
                    settings.region_id_field,
                    settings.region_name_field,
                    settings.region_population_field,
                )
            elif settings.demo_mode:
                collection = region_tools.simulated_regions(seed=settings.seed % 1000)
            else:
                self._unavailable_reason = (
                    "No region boundaries are configured. Set REGIONS_GEOJSON_PATH (see docs/setup.md)."
                )
                return
            table = region_tools.region_table(collection)
            geometry_simulated = bool(collection["metadata"]["simulated_geometry"])
            self.db.execute("DELETE FROM regions")
            self.db.insert_many(
                "regions",
                [
                    {
                        "region_id": r["region_id"],
                        "name": r["name"],
                        "population": r["population"],
                        "geometry": r["geometry"],
                        "centroid_lon": r["centroid_lon"],
                        "centroid_lat": r["centroid_lat"],
                        "neighbours": r["neighbours"],
                        "is_simulated": geometry_simulated,
                    }
                    for r in table
                ],
            )

            region_ids = [r["region_id"] for r in table]
            if settings.surveillance_reports_csv:
                frame = pd.read_csv(settings.surveillance_reports_csv)
                frame = validate_reports(frame, region_ids, hospital_ids, settings.suppression_threshold)
                self._replace_reports(frame, is_simulated=False)
            elif settings.demo_mode:
                end_week = last_complete_week()
                latest = self.db.fetch_one(
                    "SELECT MAX(week_start) AS week FROM surveillance_reports WHERE is_simulated = :flag",
                    {"flag": True},
                )
                if not latest or latest["week"] != end_week.isoformat():
                    frame = simulate_reports(
                        table,
                        hospital_ids,
                        end_week,
                        settings.surveillance_weeks,
                        settings.seed,
                        settings.suppression_threshold,
                    )
                    self._replace_reports(frame, is_simulated=True)
            else:
                self._unavailable_reason = "No aggregated surveillance reports are configured. Set SURVEILLANCE_REPORTS_CSV (see docs/setup.md)."
                return
            self._unavailable_reason = None
        except (FileNotFoundError, ValueError, ReportValidationError, RuntimeError) as exc:
            self._unavailable_reason = f"Surveillance data could not be loaded: {exc}"

    def _replace_reports(self, frame: pd.DataFrame, is_simulated: bool) -> None:
        rows = []
        for record in frame.to_dict("records"):
            count = record["case_count"]
            rows.append(
                {
                    "hospital_id": record["hospital_id"],
                    "region_id": record["region_id"],
                    "disease": record["disease"],
                    "week_start": record["week_start"],
                    "case_count": None if pd.isna(count) else int(count),
                    "suppressed": bool(record["suppressed"]),
                    "is_simulated": is_simulated,
                }
            )
        with self.db.transaction():
            self.db.execute("DELETE FROM surveillance_reports")
            self.db.execute("DELETE FROM analytics_results WHERE kind = 'hotspot'")
            self.db.execute("DELETE FROM forecasts")
        self.db.insert_many("surveillance_reports", rows)
        self._series_cache.clear()

    def _require_available(self) -> None:
        if self._unavailable_reason:
            raise UnavailableError(self._unavailable_reason)
        if self.db.fetch_one("SELECT COUNT(*) AS n FROM surveillance_reports")["n"] == 0:
            raise UnavailableError("No aggregated surveillance reports have been loaded.")

    # ================================================================= data
    def is_simulated(self) -> bool:
        row = self.db.fetch_one(
            "SELECT COUNT(*) AS n FROM surveillance_reports WHERE is_simulated = :flag", {"flag": True}
        )
        return bool(row["n"])

    def geometry_simulated(self) -> bool:
        row = self.db.fetch_one("SELECT COUNT(*) AS n FROM regions WHERE is_simulated = :flag", {"flag": True})
        return bool(row["n"])

    def regions(self) -> List[Dict[str, Any]]:
        return self.db.fetch_all("SELECT * FROM regions ORDER BY region_id")

    def diseases(self) -> List[Dict[str, str]]:
        rows = self.db.fetch_all("SELECT DISTINCT disease FROM surveillance_reports ORDER BY disease")
        known = list(DISEASES)
        rows.sort(
            key=lambda row: (known.index(row["disease"]) if row["disease"] in known else len(known), row["disease"])
        )
        return [
            {
                "id": row["disease"],
                "label": DISEASES.get(row["disease"], {}).get("label", row["disease"].replace("_", " ").title()),
            }
            for row in rows
        ]

    def _data_version(self) -> str:
        row = self.db.fetch_one(
            "SELECT COUNT(*) AS n, MAX(week_start) AS latest, MAX(id) AS last_id FROM surveillance_reports"
        )
        return f"{row['n']}:{row['latest']}:{row['last_id']}"

    def regional_series(self, disease: str) -> Dict[str, Any]:
        """Weekly regional series for one disease: weeks (oldest first) and per-region values."""
        version = self._data_version()
        cached = self._series_cache.get(disease)
        if cached and cached[0] == version:
            return cached[1]
        rows = self.db.fetch_all(
            "SELECT hospital_id, region_id, disease, week_start, case_count, suppressed FROM surveillance_reports "
            "WHERE disease = :disease",
            {"disease": disease},
        )
        if not rows:
            raise NotFoundError(f"No surveillance reports for disease '{disease}'")
        aggregated = aggregate_regional(pd.DataFrame(rows))
        weeks = sorted(aggregated["week_start"].unique())
        position = {week: index for index, week in enumerate(weeks)}
        counts: Dict[str, List[Optional[int]]] = {}
        details: Dict[str, List[dict]] = {}
        for region_id, group in aggregated.groupby("region_id"):
            values: List[Optional[int]] = [None] * len(weeks)
            meta: List[dict] = [{"reporting_hospitals": 0, "suppressed_cells": 0} for _ in weeks]
            for record in group.to_dict("records"):
                index = position[record["week_start"]]
                values[index] = None if pd.isna(record["case_count"]) else int(record["case_count"])
                meta[index] = {
                    "reporting_hospitals": int(record["reporting_hospitals"]),
                    "suppressed_cells": int(record["suppressed_cells"]),
                }
            counts[region_id] = values
            details[region_id] = meta
        result = {"weeks": weeks, "counts": counts, "details": details}
        self._series_cache[disease] = (version, result)
        return result

    @staticmethod
    def _period(week_start: str) -> Dict[str, str]:
        start = date.fromisoformat(week_start)
        return {
            "week_start": week_start,
            "week_end": (start + timedelta(days=6)).isoformat(),
            "label": iso_week_label(start),
        }

    def data_status(self) -> Dict[str, Any]:
        simulated = self.is_simulated()
        return {
            "simulated": simulated,
            "label": self.settings.simulated_label if simulated else "Aggregated reports from configured source",
            "geometry_simulated": self.geometry_simulated(),
            "suppression_threshold": self.settings.suppression_threshold,
        }

    # ============================================================== options
    def options(self) -> Dict[str, Any]:
        self._require_available()
        diseases = self.diseases()
        weeks = self.regional_series(diseases[0]["id"])["weeks"]
        return {
            "diseases": diseases,
            "regions": [
                {"region_id": r["region_id"], "name": r["name"], "population": r["population"]} for r in self.regions()
            ],
            "periods": [self._period(week) for week in reversed(weeks[-26:])],
            "latest_period": self._period(weeks[-1]),
            "data_status": self.data_status(),
        }

    # ============================================================= hotspots
    def hotspots(
        self, disease: Optional[str] = None, period: Optional[str] = None, actor: str = "system"
    ) -> Dict[str, Any]:
        self._require_available()
        diseases = self.diseases()
        disease = disease or diseases[0]["id"]
        disease_info = next((d for d in diseases if d["id"] == disease), None)
        if disease_info is None:
            raise NotFoundError(f"Unknown disease '{disease}'")
        series = self.regional_series(disease)
        weeks = series["weeks"]
        period = period or weeks[-1]
        if period not in weeks:
            raise ValidationFailed(f"No data for the week starting {period}")
        index = weeks.index(period)

        key = f"{disease}:{period}"
        version = self._data_version()
        cached = self.db.fetch_one(
            "SELECT payload FROM analytics_results WHERE kind = 'hotspot' AND result_key = :key", {"key": key}
        )
        if cached and cached["payload"].get("data_version") == version:
            return cached["payload"]

        regions = self.regions()
        neighbours = {r["region_id"]: r["neighbours"] or [] for r in regions}
        detected = detect_hotspots(series["counts"], index, neighbours, self.params)
        time_period = self._period(period)

        results, features = [], []
        for region in regions:
            region_id = region["region_id"]
            result = detected.get(region_id) or {
                "case_count": None,
                "baseline_mean": None,
                "baseline_std": None,
                "baseline_points": 0,
                "anomaly_score": None,
                "status": INSUFFICIENT_DATA,
                "hotspot_flag": False,
                "reason": "No reports were received for this region.",
                "isolation_forest_score": None,
                "cluster_id": None,
                "adjacent_flagged_regions": [],
            }
            counts = series["counts"].get(region_id, [None] * len(weeks))
            meta = series["details"].get(region_id, [{}] * len(weeks))[index] if region_id in series["details"] else {}
            first = max(0, index - 11)
            record = {
                "region_id": region_id,
                "region_name": region["name"],
                "population": region["population"],
                "disease": disease,
                "time_period": time_period["label"],
                "case_count": result["case_count"],
                "case_rate": case_rate_per_100k(result["case_count"], region["population"]),
                "anomaly_score": result["anomaly_score"],
                "hotspot_flag": result["hotspot_flag"],
                "status": result["status"],
                "status_label": STATUS_LABELS[result["status"]],
                "reason": result["reason"],
                "baseline_mean": result["baseline_mean"],
                "baseline_std": result["baseline_std"],
                "baseline_points": result["baseline_points"],
                "isolation_forest_score": result["isolation_forest_score"],
                "cluster_id": result["cluster_id"],
                "adjacent_flagged_regions": result["adjacent_flagged_regions"],
                "reporting_hospitals": meta.get("reporting_hospitals", 0),
                "suppressed_cells": meta.get("suppressed_cells", 0),
                "recent_weeks": [self._period(w)["label"] for w in weeks[first : index + 1]],
                "recent_counts": counts[first : index + 1],
            }
            results.append(record)
            features.append(
                {
                    "type": "Feature",
                    "geometry": region["geometry"],
                    "properties": {
                        k: record[k]
                        for k in (
                            "region_id",
                            "region_name",
                            "status",
                            "status_label",
                            "case_count",
                            "case_rate",
                            "anomaly_score",
                            "hotspot_flag",
                            "cluster_id",
                        )
                    },
                }
            )

        summary = {
            status: sum(1 for r in results if r["status"] == status)
            for status in (CANDIDATE_HOTSPOT, ELEVATED, NORMAL, INSUFFICIENT_DATA)
        }
        payload = {
            "disease": disease_info,
            "time_period": time_period,
            "method": self.params.describe(),
            "regions": results,
            "geojson": {"type": "FeatureCollection", "features": features},
            "summary": summary,
            "disclaimer": HOTSPOT_DISCLAIMER,
            "data_status": self.data_status(),
            "generated_at": utc_now_iso(),
            "data_version": version,
        }
        self.db.execute(
            "INSERT INTO analytics_results (kind, result_key, payload, model_version, is_simulated, generated_at) "
            "VALUES ('hotspot', :key, :payload, NULL, :simulated, :now) "
            "ON CONFLICT (kind, result_key) DO UPDATE SET payload = excluded.payload, "
            "is_simulated = excluded.is_simulated, generated_at = excluded.generated_at",
            {"key": key, "payload": payload, "simulated": self.is_simulated(), "now": payload["generated_at"]},
        )
        self.audit.record(
            "ANALYTICS_GENERATED",
            actor,
            details={
                "kind": "hotspot candidates",
                "disease": disease,
                "time_period": time_period["label"],
                "candidates": summary[CANDIDATE_HOTSPOT],
            },
        )
        return payload

    # ============================================================= overview
    def overview(self, actor: str = "system") -> Dict[str, Any]:
        """Latest-week summary across diseases, for the dashboard."""
        self._require_available()
        diseases = []
        for disease in self.diseases():
            result = self.hotspots(disease["id"], None, actor)
            flagged = [
                {
                    "region_id": r["region_id"],
                    "region_name": r["region_name"],
                    "status": r["status"],
                    "status_label": r["status_label"],
                    "case_count": r["case_count"],
                    "anomaly_score": r["anomaly_score"],
                }
                for r in result["regions"]
                if r["status"] in (CANDIDATE_HOTSPOT, ELEVATED)
            ]
            flagged.sort(key=lambda r: -(r["anomaly_score"] or 0))
            complete = [r["case_count"] for r in result["regions"] if r["case_count"] is not None]
            diseases.append(
                {
                    "disease": disease,
                    "time_period": result["time_period"],
                    "summary": result["summary"],
                    "reported_cases": int(sum(complete)),
                    "regions_with_complete_counts": len(complete),
                    "regions_total": len(result["regions"]),
                    "flagged_regions": flagged[:5],
                }
            )
        return {"diseases": diseases, "disclaimer": HOTSPOT_DISCLAIMER, "data_status": self.data_status()}
