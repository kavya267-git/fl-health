"""Forecast API logic for regional weekly case counts."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from analytics.forecasting.pipeline import InsufficientDataError, forecast_series
from analytics.geospatial.surveillance import iso_week_label
from app.analytics.surveillance_service import SurveillanceService
from app.database import Database
from app.services.audit_service import AuditService
from app.services.permissions import ensure_region_scope
from app.utils.errors import NotFoundError, PermissionDenied, ValidationFailed
from app.utils.time import utc_now_iso

FORECAST_DISCLAIMER = (
    "Forecast / Prediction. These values are a statistical model's projection from past weekly counts, "
    "shown with an uncertainty interval. They are not confirmed future cases."
)


class ForecastService:
    def __init__(self, db: Database, audit: AuditService, surveillance: SurveillanceService):
        self.db = db
        self.audit = audit
        self.surveillance = surveillance

    def forecast(
        self,
        region_id: Optional[str],
        disease: Optional[str],
        horizon: int = 8,
        actor: str = "system",
        jurisdiction: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Forecast for one region and disease. ``jurisdiction`` (a health officer's region ids) limits which
        regions may be asked for, and the default region is chosen among them."""
        if horizon < 1 or horizon > 26:
            raise ValidationFailed("horizon must be between 1 and 26 weeks")
        self.surveillance._require_available()
        diseases = self.surveillance.diseases()
        disease = disease or diseases[0]["id"]
        disease_info = next((d for d in diseases if d["id"] == disease), None)
        if disease_info is None:
            raise NotFoundError(f"Unknown disease '{disease}'")
        regions = {r["region_id"]: r for r in self.surveillance.regions()}
        series = self.surveillance.regional_series(disease)
        if jurisdiction is not None:
            if region_id is not None and region_id in regions:
                ensure_region_scope({"role": "health_officer", "jurisdiction": jurisdiction}, [region_id])
            regions = {k: v for k, v in regions.items() if k in jurisdiction}
            if not regions:
                raise PermissionDenied("Your jurisdiction has no regions. Ask an administrator to set it.")

        if region_id is None:
            # Default to the region with the most complete history.
            region_id = max(regions, key=lambda r: sum(v is not None for v in series["counts"].get(r, [])))
        if region_id not in regions:
            raise NotFoundError(f"Unknown region '{region_id}'")
        region = regions[region_id]
        weeks = series["weeks"]
        values = series["counts"].get(region_id, [None] * len(weeks))
        base = {
            "region_id": region_id,
            "region_name": region["name"],
            "disease": disease_info,
            "forecast_horizon": horizon,
            "disclaimer": FORECAST_DISCLAIMER,
            "data_status": self.surveillance.data_status(),
            "data_through": weeks[-1],
        }

        version = self.surveillance._data_version()
        cached = self.db.fetch_one(
            "SELECT payload FROM forecasts WHERE region_id = :region AND disease = :disease AND horizon = :horizon",
            {"region": region_id, "disease": disease, "horizon": horizon},
        )
        if cached and cached["payload"].get("data_version") == version:
            return cached["payload"]

        try:
            result = forecast_series(values, horizon)
        except InsufficientDataError as exc:
            return {
                **base,
                "available": False,
                "reason": str(exc),
                "history": [
                    {"week_start": week, "label": iso_week_label(date.fromisoformat(week)), "case_count": value}
                    for week, value in zip(weeks, values)
                ],
            }

        last = date.fromisoformat(weeks[-1])
        test_size = result["evaluation_metrics"]["test_size"]
        holdout = result["evaluation_metrics"].pop("holdout_prediction")
        history = []
        for index, (week, observed, used) in enumerate(zip(weeks, values, result["history_used"])):
            holdout_index = index - (len(weeks) - test_size)
            history.append(
                {
                    "week_start": week,
                    "label": iso_week_label(date.fromisoformat(week)),
                    "case_count": observed,
                    "imputed": observed is None,
                    "value_used": used,
                    "holdout_prediction": holdout[holdout_index] if holdout_index >= 0 else None,
                }
            )
        intervals = result["uncertainty_interval"]
        points = []
        for step in range(horizon):
            start = last + timedelta(days=7 * (step + 1))
            points.append(
                {
                    "week_start": start.isoformat(),
                    "label": iso_week_label(start),
                    "predicted": result["predicted_values"][step],
                    "lower_80": intervals["level_80"]["lower"][step],
                    "upper_80": intervals["level_80"]["upper"][step],
                    "lower_95": intervals["level_95"]["lower"][step],
                    "upper_95": intervals["level_95"]["upper"][step],
                }
            )
        payload = {
            **base,
            "available": True,
            "reason": None,
            "model_name": result["model_name"],
            "predicted_values": result["predicted_values"],
            "uncertainty_interval": intervals,
            "evaluation_metrics": result["evaluation_metrics"],
            "candidates": result["candidates"],
            "history": history,
            "forecast": points,
            "imputed_points": result["imputed_points"],
            "generated_at": utc_now_iso(),
            "data_version": version,
        }
        self.db.execute(
            "INSERT INTO forecasts (region_id, disease, horizon, model_name, payload, data_through, is_simulated, generated_at) "
            "VALUES (:region, :disease, :horizon, :model, :payload, :through, :simulated, :now) "
            "ON CONFLICT (region_id, disease, horizon) DO UPDATE SET model_name = excluded.model_name, "
            "payload = excluded.payload, data_through = excluded.data_through, "
            "is_simulated = excluded.is_simulated, generated_at = excluded.generated_at",
            {
                "region": region_id,
                "disease": disease,
                "horizon": horizon,
                "model": payload["model_name"],
                "payload": payload,
                "through": weeks[-1],
                "simulated": self.surveillance.is_simulated(),
                "now": payload["generated_at"],
            },
        )
        self.audit.record(
            "FORECAST_GENERATED",
            actor,
            details={
                "region_id": region_id,
                "disease": disease,
                "horizon": horizon,
                "model": payload["model_name"],
                "mae": payload["evaluation_metrics"]["mae"],
                "rmse": payload["evaluation_metrics"]["rmse"],
            },
        )
        return payload
