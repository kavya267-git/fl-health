"""Hospital bed projection from a regional forecast: plain arithmetic, so it can be checked by hand.

For one hospital and one disease, over the next weeks (week 1 = the first week after the latest data):

1. **Hospital share** of each region it reports for: this hospital's reported cases divided by the region's
   reported cases over the last 8 weeks, using only weeks where both are known (a suppressed cell or an
   incomplete regional total leaves that week out).
2. **Weekly admissions** = sum over those regions of (regional forecast x share) x the disease's admission
   rate. The low and high values use the forecast's 80% likely range instead of its central value.
3. **Beds occupied** in a week: every patient admitted in a week is assumed to arrive at the start of that week
   and to stay ``length_of_stay_days`` days. A cohort therefore fills beds for its first 7 days, then carries
   over into later weeks until its stay ends. Average beds in a week = patient-days falling in that week / 7.
   ICU beds use the same rule for the ICU share of admissions.
4. **Total** = beds occupied today (current occupancy % x total beds) + the projected beds; it is compared
   with the hospital's beds. Today's patients are assumed to stay, which errs on the side of caution.

Nothing here invents a number: a region without a forecast or without a usable share is reported as missing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

SHARE_WEEKS = 8


@dataclass(frozen=True)
class DiseaseAssumptions:
    admission_rate: float  # share of cases admitted to hospital
    icu_share: float  # share of admitted patients who need an ICU bed
    length_of_stay_days: float  # average stay, in days


def hospital_share(hospital_counts: Sequence[Optional[float]], regional_counts: Sequence[Optional[float]], weeks: int = SHARE_WEEKS) -> Optional[float]:
    """This hospital's share of a region's cases over the last ``weeks`` weeks (weeks with both counts known).

    Returns None when no week has both counts, or the region reported no cases in those weeks.
    """
    pairs = [
        (h, r)
        for h, r in zip(list(hospital_counts)[-weeks:], list(regional_counts)[-weeks:])
        if h is not None and r is not None
    ]
    regional = sum(r for _, r in pairs)
    if not pairs or regional <= 0:
        return None
    return min(sum(h for h, _ in pairs) / regional, 1.0)


def weekly_admissions(regional_forecasts: Dict[str, Sequence[float]], shares: Dict[str, float], admission_rate: float) -> List[float]:
    """Admissions per week: sum over regions of forecast x share x admission rate."""
    horizon = len(next(iter(regional_forecasts.values()))) if regional_forecasts else 0
    return [
        sum(regional_forecasts[region][week] * shares[region] for region in regional_forecasts) * admission_rate
        for week in range(horizon)
    ]


def beds_occupied(admissions: Sequence[float], length_of_stay_days: float) -> List[float]:
    """Average beds occupied in each week, with stays carrying over from earlier weeks.

    A cohort admitted at the start of week ``w`` is in hospital on days [7w, 7w + L). The beds it fills in week
    ``t`` are the days of that interval falling in week t, divided by 7.
    """
    if length_of_stay_days < 0:
        raise ValueError("length of stay cannot be negative")
    result = []
    for week in range(len(admissions)):
        start, end = 7 * week, 7 * week + 7
        beds = 0.0
        for cohort_week, cohort in enumerate(admissions[: week + 1]):
            stay_start, stay_end = 7 * cohort_week, 7 * cohort_week + length_of_stay_days
            overlap = max(0.0, min(end, stay_end) - max(start, stay_start))
            beds += cohort * overlap / 7
        result.append(beds)
    return result


def project(
    regional_forecasts: Dict[str, Dict[str, Sequence[float]]],
    shares: Dict[str, float],
    assumptions: DiseaseAssumptions,
    current_occupied: float,
) -> Dict[str, List[float]]:
    """Admissions, beds, ICU beds and total beds per week for the low, central and high forecast.

    ``regional_forecasts`` maps a region to {"low": [...], "mid": [...], "high": [...]} (one value per week).
    """
    out: Dict[str, List[float]] = {}
    for level in ("low", "mid", "high"):
        forecasts = {region: values[level] for region, values in regional_forecasts.items()}
        admitted = weekly_admissions(forecasts, shares, assumptions.admission_rate)
        beds = beds_occupied(admitted, assumptions.length_of_stay_days)
        icu = beds_occupied([a * assumptions.icu_share for a in admitted], assumptions.length_of_stay_days)
        out[f"admissions_{level}"] = admitted
        out[f"beds_{level}"] = beds
        out[f"icu_beds_{level}"] = icu
        out[f"total_beds_{level}"] = [current_occupied + b for b in beds]
    return out
