"""Hotspot-candidate detection on regional weekly counts.

Baseline method (transparent by design): a historical z-score in the style of
the CDC EARS C2 algorithm, adapted to weekly data. For each region and week,

    z = (count - mean(baseline)) / max(std(baseline), std_floor)

where the baseline is the ``baseline_weeks`` weeks that end ``guard_weeks``
before the week being tested. The guard gap stops the start of a rise from
inflating its own baseline.

A flag means "this week is statistically unusual for this region". It is a
prompt for a person to look closer - NOT a confirmed outbreak.

An Isolation Forest score is also reported as a second opinion. It never
changes the flag.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

import numpy as np

from analytics.geospatial.geometry import connected_groups

NORMAL = "NORMAL"
ELEVATED = "ELEVATED"
CANDIDATE_HOTSPOT = "CANDIDATE_HOTSPOT"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

STATUS_LABELS = {
    NORMAL: "Normal",
    ELEVATED: "Elevated",
    CANDIDATE_HOTSPOT: "Potential hotspot",
    INSUFFICIENT_DATA: "Insufficient data",
}

METHOD_NAME = "Historical z-score (EARS C2 style, weekly)"


@dataclass(frozen=True)
class HotspotParams:
    baseline_weeks: int = 8
    guard_weeks: int = 1
    min_baseline_points: int = 6
    elevated_z: float = 2.0
    candidate_z: float = 3.0
    min_cases: int = 5
    std_floor: float = 1.0

    def describe(self) -> dict:
        return {
            "method": METHOD_NAME,
            "baseline_weeks": self.baseline_weeks,
            "guard_weeks": self.guard_weeks,
            "min_baseline_points": self.min_baseline_points,
            "elevated_threshold_z": self.elevated_z,
            "candidate_threshold_z": self.candidate_z,
            "min_cases_for_candidate": self.min_cases,
            "std_floor": self.std_floor,
        }


def zscore_for_week(series: Sequence[Optional[float]], index: int, params: HotspotParams = HotspotParams()) -> dict:
    """Score one week of one region's series. ``None`` marks a missing or suppressed week."""
    current = series[index] if 0 <= index < len(series) else None
    end = index - params.guard_weeks
    start = end - params.baseline_weeks
    baseline = [v for v in series[max(start, 0) : max(end, 0)] if v is not None]
    result = {
        "case_count": None if current is None else int(current),
        "baseline_mean": None,
        "baseline_std": None,
        "baseline_points": len(baseline),
        "anomaly_score": None,
        "status": INSUFFICIENT_DATA,
        "hotspot_flag": False,
        "reason": None,
    }
    if current is None:
        result["reason"] = "The count for this week is missing or suppressed."
        return result
    if len(baseline) < params.min_baseline_points:
        result["reason"] = f"Only {len(baseline)} usable baseline week(s); {params.min_baseline_points} are required."
        return result

    mean = float(np.mean(baseline))
    std = float(np.std(baseline, ddof=1)) if len(baseline) > 1 else 0.0
    z = (float(current) - mean) / max(std, params.std_floor)
    result.update({"baseline_mean": mean, "baseline_std": std, "anomaly_score": float(z)})
    if z >= params.candidate_z and current >= params.min_cases:
        result.update({"status": CANDIDATE_HOTSPOT, "hotspot_flag": True})
        result["reason"] = f"{z:.1f} standard deviations above the recent baseline of {mean:.1f} cases/week."
    elif z >= params.elevated_z:
        result["status"] = ELEVATED
        result["reason"] = f"{z:.1f} standard deviations above the recent baseline of {mean:.1f} cases/week."
    else:
        result["status"] = NORMAL
        result["reason"] = "Within the range expected from recent weeks."
    return result


def isolation_forest_scores(
    region_series: Dict[str, Sequence[Optional[float]]], index: int, seed: int = 0
) -> Dict[str, Optional[float]]:
    """Second-opinion anomaly score in [0, 1]; higher is more unusual.

    Each region-week is described by its count relative to that region's own
    median and by its week-over-week change. The forest is fitted on all
    earlier weeks only, then scores the requested week.
    """
    from sklearn.ensemble import IsolationForest

    history, current, current_ids = [], [], []
    for region_id, series in region_series.items():
        values = [v for v in series[:index] if v is not None]
        if len(values) < 8:
            continue
        median = float(np.median(values)) or 1.0
        for position in range(1, index):
            if series[position] is None or series[position - 1] is None:
                continue
            history.append([series[position] / median, (series[position] - series[position - 1]) / median])
        if index < len(series) and series[index] is not None and series[index - 1] is not None:
            current.append([series[index] / median, (series[index] - series[index - 1]) / median])
            current_ids.append(region_id)
    scores: Dict[str, Optional[float]] = {region_id: None for region_id in region_series}
    if len(history) < 50 or not current:
        return scores
    forest = IsolationForest(n_estimators=100, contamination="auto", random_state=seed).fit(np.array(history))
    raw = -forest.score_samples(np.array(current))  # roughly in [0.3, 1.0]
    for region_id, value in zip(current_ids, raw):
        scores[region_id] = float(np.clip(value, 0.0, 1.0))
    return scores


def detect_hotspots(
    region_series: Dict[str, Sequence[Optional[float]]],
    index: int,
    neighbours: Optional[Dict[str, List[str]]] = None,
    params: HotspotParams = HotspotParams(),
    with_isolation_forest: bool = True,
) -> Dict[str, dict]:
    """Score every region for the week at ``index``.

    ``region_series`` maps region id -> weekly counts (oldest first, ``None``
    for missing/suppressed weeks). Flagged regions that border each other are
    grouped so they can be reviewed together.
    """
    results = {region_id: zscore_for_week(series, index, params) for region_id, series in region_series.items()}
    forest = isolation_forest_scores(region_series, index) if with_isolation_forest else {}
    for region_id, result in results.items():
        result["isolation_forest_score"] = forest.get(region_id)
        result["cluster_id"] = None
        result["adjacent_flagged_regions"] = []

    if neighbours:
        raised = [r for r, result in results.items() if result["status"] in (ELEVATED, CANDIDATE_HOTSPOT)]
        for number, group in enumerate(connected_groups(raised, neighbours), start=1):
            if len(group) < 2:
                continue
            for region_id in group:
                results[region_id]["cluster_id"] = f"C{number}"
                results[region_id]["adjacent_flagged_regions"] = [r for r in group if r != region_id]
    return results
