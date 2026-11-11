"""Aggregated disease surveillance data.

Hospitals report *weekly case counts per region and disease* - never
patient-level records or locations. Counts between 1 and 4 are suppressed at
the hospital before they are reported.

This module provides:

* a simulated generator for demo mode (SIMULATED DATA),
* validation for hospital reports loaded from a file in real mode,
* aggregation of hospital reports into regional weekly series.
"""

from __future__ import annotations

import zlib
from datetime import date, timedelta
from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

from analytics.privacy.suppression import DEFAULT_SUPPRESSION_THRESHOLD, suppress_small_count

DISEASES = {
    "influenza_like_illness": {
        "label": "Influenza-like illness",
        "weekly_rate_per_100k": 40.0,
        "seasonal_amplitude": 0.50,
        "peak_week": 3,  # winter peak
    },
    "dengue": {
        "label": "Dengue",
        "weekly_rate_per_100k": 24.0,
        "seasonal_amplitude": 0.55,
        "peak_week": 38,  # late-monsoon peak
    },
    "acute_gastroenteritis": {
        "label": "Acute gastroenteritis",
        "weekly_rate_per_100k": 14.0,
        "seasonal_amplitude": 0.20,
        "peak_week": 26,
    },
}

REPORT_COLUMNS = ["hospital_id", "region_id", "disease", "week_start", "case_count", "suppressed"]


def week_start(day: date) -> date:
    """Monday of the ISO week containing ``day``."""
    return day - timedelta(days=day.weekday())


def last_complete_week(today: Optional[date] = None) -> date:
    today = today or date.today()
    return week_start(today) - timedelta(days=7)


def iso_week_label(start: date) -> str:
    year, week, _ = start.isocalendar()
    return f"{year}-W{week:02d}"


def assign_catchments(
    regions: List[dict], hospital_ids: List[str], home_regions: Optional[Dict[str, str]] = None
) -> Dict[str, Dict[str, float]]:
    """Share of each region's cases seen by each hospital (simulation only).

    Each hospital sits in a home region: ``home_regions[hospital_id]`` when given, otherwise evenly spread
    regions. Every region is served by its two nearest hospitals with a 70/30 split.
    """
    ordered = sorted(regions, key=lambda r: r["region_id"])
    step = len(ordered) / len(hospital_ids)
    sites = {hospital_id: ordered[int(index * step + step / 2)] for index, hospital_id in enumerate(hospital_ids)}
    if home_regions:
        by_id = {r["region_id"]: r for r in ordered}
        unknown = sorted(f"{h}:{r}" for h, r in home_regions.items() if h in sites and r not in by_id)
        if unknown:
            raise ValueError(f"Unknown home region(s) for the simulated hospitals: {', '.join(unknown)}")
        sites.update({h: by_id[r] for h, r in home_regions.items() if h in sites})
    shares: Dict[str, Dict[str, float]] = {}
    for region in ordered:
        distances = sorted(
            (
                (region["centroid_lon"] - site["centroid_lon"]) ** 2
                + (region["centroid_lat"] - site["centroid_lat"]) ** 2,
                hospital_id,
            )
            for hospital_id, site in sites.items()
        )
        shares[region["region_id"]] = {distances[0][1]: 0.7, distances[1][1]: 0.3}
    return shares


def simulate_reports(
    regions: List[dict],
    hospital_ids: List[str],
    end_week: date,
    weeks: int = 104,
    seed: int = 2024,
    suppression_threshold: int = DEFAULT_SUPPRESSION_THRESHOLD,
    home_regions: Optional[Dict[str, str]] = None,
) -> pd.DataFrame:
    """SIMULATED hospital-level weekly reports.

    Seasonal baselines with over-dispersed noise, plus recent rises injected in
    a few regions so the hotspot layer has something to find. The rises are
    synthetic and do not represent any real event.
    """
    rng = np.random.default_rng([seed, zlib.crc32(end_week.isoformat().encode())])
    ordered = sorted(regions, key=lambda r: r["region_id"])
    shares = assign_catchments(ordered, hospital_ids, home_regions)
    week_starts = [end_week - timedelta(days=7 * offset) for offset in range(weeks - 1, -1, -1)]

    # Injected rises: (disease, region, multiplier at the latest week, weeks of ramp-up).
    # The most populous region and its most populous neighbour get a dengue
    # rise; the largest region that borders neither gets a milder influenza rise.
    by_id = {r["region_id"]: r for r in ordered}
    by_population = sorted(ordered, key=lambda r: (-(r["population"] or 0), r["region_id"]))
    focus = by_population[0]
    focus_neighbours = sorted(
        (by_id[n] for n in focus["neighbours"]), key=lambda r: (-(r["population"] or 0), r["region_id"])
    )
    rises = [("dengue", focus["region_id"], 3.2, 4)]
    excluded = {focus["region_id"]}
    if focus_neighbours:
        rises.append(("dengue", focus_neighbours[0]["region_id"], 2.6, 3))
        excluded.update(n["region_id"] for n in focus_neighbours)
    for region in by_population:
        if region["region_id"] not in excluded:
            rises.append(("influenza_like_illness", region["region_id"], 1.9, 3))
            break

    rows = []
    for disease, spec in DISEASES.items():
        for region in ordered:
            population = region["population"] or 100_000
            region_factor = float(np.exp(rng.normal(0, 0.18)))
            # Slowly varying local level (AR(1) on the log scale): a week that
            # runs above its seasonal norm tends to be followed by another.
            local_level = 0.0
            for position, start in enumerate(week_starts):
                iso_week = start.isocalendar()[1]
                seasonal = 1.0 + spec["seasonal_amplitude"] * np.cos(2 * np.pi * (iso_week - spec["peak_week"]) / 52.0)
                local_level = 0.8 * local_level + rng.normal(0, 0.09)
                expected = (
                    spec["weekly_rate_per_100k"]
                    * population
                    / 100_000
                    * region_factor
                    * max(seasonal, 0.08)
                    * float(np.exp(local_level))
                )
                weeks_from_end = len(week_starts) - 1 - position
                for rise_disease, rise_region, multiplier, ramp in rises:
                    if rise_disease == disease and rise_region == region["region_id"] and weeks_from_end < ramp:
                        progress = (ramp - weeks_from_end) / ramp
                        expected *= 1.0 + (multiplier - 1.0) * progress
                for hospital_id, share in shares[region["region_id"]].items():
                    mean = expected * share
                    dispersion = 30.0  # negative-binomial size; smaller = noisier
                    count = int(rng.negative_binomial(dispersion, dispersion / (dispersion + mean))) if mean > 0 else 0
                    reported, suppressed = suppress_small_count(count, suppression_threshold)
                    rows.append((hospital_id, region["region_id"], disease, start.isoformat(), reported, suppressed))
    frame = pd.DataFrame(rows, columns=REPORT_COLUMNS)
    frame["case_count"] = frame["case_count"].astype("Int64")
    return frame


class ReportValidationError(ValueError):
    def __init__(self, problems: List[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


def validate_reports(
    frame: pd.DataFrame,
    known_regions: Iterable[str],
    known_hospitals: Iterable[str],
    suppression_threshold: int = DEFAULT_SUPPRESSION_THRESHOLD,
) -> pd.DataFrame:
    """Check hospital reports before they are stored. Raises with every problem found."""
    problems = []
    missing = [c for c in REPORT_COLUMNS if c not in frame.columns and c != "suppressed"]
    if missing:
        raise ReportValidationError([f"Missing columns: {missing}"])
    frame = frame.copy()
    if "suppressed" not in frame.columns:
        frame["suppressed"] = frame["case_count"].isna()
    frame["suppressed"] = frame["suppressed"].astype(bool)

    unknown_regions = sorted(set(frame["region_id"]) - set(known_regions))
    if unknown_regions:
        problems.append(f"Unknown region ids: {unknown_regions[:5]}")
    unknown_hospitals = sorted(set(frame["hospital_id"]) - set(known_hospitals))
    if unknown_hospitals:
        problems.append(f"Unknown hospital ids: {unknown_hospitals[:5]}")

    parsed = pd.to_datetime(frame["week_start"], errors="coerce")
    if parsed.isna().any():
        problems.append(f"{int(parsed.isna().sum())} row(s) have an unreadable week_start date")
    else:
        if (parsed.dt.weekday != 0).any():
            problems.append("week_start must be a Monday (ISO week start)")
        frame["week_start"] = parsed.dt.strftime("%Y-%m-%d")

    counts = pd.to_numeric(frame["case_count"], errors="coerce")
    present = counts.dropna()
    if (present < 0).any():
        problems.append("case_count cannot be negative")
    if (present != present.round()).any():
        problems.append("case_count must be a whole number")
    if ((present > 0) & (present < suppression_threshold)).any():
        problems.append(f"Counts between 1 and {suppression_threshold - 1} must be suppressed before reporting")
    if (counts.isna() & ~frame["suppressed"]).any():
        problems.append("Rows without a case_count must be marked suppressed")
    if frame.duplicated(["hospital_id", "region_id", "disease", "week_start"]).any():
        problems.append("Duplicate rows for the same hospital, region, disease and week")

    if problems:
        raise ReportValidationError(problems)
    frame["case_count"] = counts.astype("Int64")
    return frame[REPORT_COLUMNS]


def aggregate_regional(frame: pd.DataFrame) -> pd.DataFrame:
    """Combine hospital reports into one row per region, disease and week.

    If any contributing hospital cell is suppressed the regional total is only
    a lower bound, so ``case_count`` is left empty and ``complete`` is False.
    """
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "region_id",
                "disease",
                "week_start",
                "case_count",
                "complete",
                "reporting_hospitals",
                "suppressed_cells",
            ]
        )
    working = frame.copy()
    working["suppressed"] = working["suppressed"].astype(bool)
    working["count_filled"] = pd.to_numeric(working["case_count"], errors="coerce").fillna(0)
    grouped = working.groupby(["region_id", "disease", "week_start"], as_index=False).agg(
        partial_sum=("count_filled", "sum"),
        suppressed_cells=("suppressed", "sum"),
        reporting_hospitals=("hospital_id", "nunique"),
    )
    grouped["complete"] = grouped["suppressed_cells"] == 0
    grouped["case_count"] = grouped["partial_sum"].where(grouped["complete"]).astype("Int64")
    return (
        grouped[
            ["region_id", "disease", "week_start", "case_count", "complete", "reporting_hospitals", "suppressed_cells"]
        ]
        .sort_values(["disease", "region_id", "week_start"])
        .reset_index(drop=True)
    )


def case_rate_per_100k(case_count: Optional[float], population: Optional[int]) -> Optional[float]:
    """Rate per 100,000 residents, or None without a valid population denominator."""
    if case_count is None or population is None or population <= 0:
        return None
    return float(case_count) / float(population) * 100_000.0
