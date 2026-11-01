"""Analytics schemas (surveillance, forecasting, explainability, privacy)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.schemas.common import DataStatus, OpenModel


class Disease(OpenModel):
    id: str
    label: str


class TimePeriod(OpenModel):
    week_start: str
    week_end: str
    label: str


class RegionOption(OpenModel):
    region_id: str
    name: str
    population: Optional[int] = None


class AnalyticsOptions(OpenModel):
    diseases: List[Disease]
    regions: List[RegionOption]
    periods: List[TimePeriod]
    latest_period: TimePeriod
    data_status: DataStatus


class HotspotRegion(OpenModel):
    region_id: str
    region_name: str
    disease: str
    time_period: str
    case_count: Optional[int] = None
    case_rate: Optional[float] = None
    anomaly_score: Optional[float] = None
    hotspot_flag: bool
    status: str
    status_label: str


class HotspotResponse(OpenModel):
    disease: Disease
    time_period: TimePeriod
    method: Dict[str, Any]
    regions: List[HotspotRegion]
    geojson: Dict[str, Any]
    summary: Dict[str, int]
    disclaimer: str
    data_status: DataStatus


class ForecastResponse(OpenModel):
    available: bool
    reason: Optional[str] = None
    region_id: str
    region_name: str
    disease: Disease
    forecast_horizon: int
    model_name: Optional[str] = None
    predicted_values: Optional[List[float]] = None
    evaluation_metrics: Optional[Dict[str, Any]] = None
    uncertainty_interval: Optional[Dict[str, Any]] = None
    history: List[Dict[str, Any]]
    disclaimer: str
    data_status: DataStatus


class ExplainabilityResponse(OpenModel):
    modality: str
    scope: str
    available: bool
    reason: Optional[str] = None
    explanation: Optional[Dict[str, Any]] = None
    model: Optional[Dict[str, Any]] = None
    cases: List[Dict[str, Any]]
    reference_note: str


class OverviewResponse(OpenModel):
    kpis: Dict[str, Any]
    models: List[Dict[str, Any]]
    active_rounds: List[Dict[str, Any]]
    recent_rounds: List[Dict[str, Any]]
    hospitals: List[Dict[str, Any]]
    surveillance: Dict[str, Any]
    forecast: Dict[str, Any]
    recent_activity: List[Dict[str, Any]]
    data_status: DataStatus


class PrivacyCheck(OpenModel):
    id: str
    title: str
    status: str
    detail: str


class PrivacyReport(OpenModel):
    statement: str
    architecture: Dict[str, Any]
    differential_privacy: Dict[str, Any]
    small_cell_suppression: Dict[str, Any]
    checks: List[PrivacyCheck]
    overall_status: str
    caveat: str
