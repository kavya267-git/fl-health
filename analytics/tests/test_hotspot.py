"""Hotspot-candidate detection."""

import numpy as np

from analytics.hotspot.detector import (
    CANDIDATE_HOTSPOT,
    ELEVATED,
    INSUFFICIENT_DATA,
    NORMAL,
    STATUS_LABELS,
    HotspotParams,
    detect_hotspots,
    zscore_for_week,
)


def _stable(n=30, level=40, seed=0):
    return [int(v) for v in np.random.default_rng(seed).poisson(level, n)]


def test_stable_series_is_normal():
    series = _stable()
    result = zscore_for_week(series, len(series) - 1)
    assert result["status"] in (NORMAL, ELEVATED) and result["hotspot_flag"] is False
    assert result["baseline_points"] == 8 and result["anomaly_score"] is not None


def test_sharp_rise_is_a_candidate_with_hand_computed_score():
    series = [10, 12, 9, 11, 10, 12, 11, 9, 10, 40]
    result = zscore_for_week(series, 9)
    baseline = series[0:8]  # eight weeks ending one week before the tested week
    expected = (40 - np.mean(baseline)) / max(np.std(baseline, ddof=1), 1.0)
    assert np.isclose(result["anomaly_score"], expected)
    assert result["status"] == CANDIDATE_HOTSPOT and result["hotspot_flag"] is True
    assert result["baseline_mean"] == np.mean(baseline)


def test_guard_week_is_excluded_from_the_baseline():
    series = [10] * 8 + [500, 12]
    # Week 8's spike sits in the guard gap for week 9, so it must not inflate the baseline.
    assert zscore_for_week(series, 9)["baseline_mean"] == 10


def test_moderate_rise_is_elevated_not_candidate():
    series = [20, 22, 18, 21, 19, 20, 22, 18, 20, 24]
    result = zscore_for_week(series, 9)
    assert 2.0 <= result["anomaly_score"] < 3.0
    assert result["status"] == ELEVATED and result["hotspot_flag"] is False


def test_small_counts_are_never_candidates():
    series = [0, 0, 0, 0, 0, 0, 0, 0, 0, 4]
    result = zscore_for_week(series, 9, HotspotParams(min_cases=5))
    assert result["status"] != CANDIDATE_HOTSPOT


def test_missing_or_short_data_is_insufficient_not_normal():
    assert zscore_for_week([10, 11, None], 2)["status"] == INSUFFICIENT_DATA
    suppressed_now = _stable() + [None]
    assert zscore_for_week(suppressed_now, len(suppressed_now) - 1)["status"] == INSUFFICIENT_DATA
    gaps = [10, None, None, None, 11, None, 12, 10, 11, 50]
    result = zscore_for_week(gaps, 9)
    assert result["status"] == INSUFFICIENT_DATA and result["anomaly_score"] is None
    assert "baseline" in result["reason"]


def test_adjacent_flagged_regions_are_grouped():
    quiet, rising = _stable(seed=1), _stable(seed=2)[:-1] + [200]
    series = {"A": rising, "B": list(rising), "C": quiet, "D": list(rising)}
    neighbours = {"A": ["B"], "B": ["A", "C"], "C": ["B", "D"], "D": ["C"]}
    results = detect_hotspots(series, len(quiet) - 1, neighbours, with_isolation_forest=False)
    assert results["A"]["cluster_id"] == results["B"]["cluster_id"] is not None
    assert results["A"]["adjacent_flagged_regions"] == ["B"]
    assert results["D"]["status"] == CANDIDATE_HOTSPOT and results["D"]["cluster_id"] is None  # isolated
    assert results["C"]["cluster_id"] is None


def test_isolation_forest_is_a_second_opinion_only():
    rng = np.random.default_rng(3)
    series = {f"R{i}": [int(v) for v in rng.poisson(30, 60)] for i in range(8)}
    series["R0"][-1] = 300
    with_forest = detect_hotspots(series, 59, {}, with_isolation_forest=True)
    without = detect_hotspots(series, 59, {}, with_isolation_forest=False)
    assert {r: v["status"] for r, v in with_forest.items()} == {r: v["status"] for r, v in without.items()}
    scores = {r: v["isolation_forest_score"] for r, v in with_forest.items()}
    assert max(scores, key=scores.get) == "R0"
    assert all(v["isolation_forest_score"] is None for v in without.values())


def test_labels_never_claim_an_outbreak():
    assert STATUS_LABELS[CANDIDATE_HOTSPOT] == "Potential hotspot"
    assert not any("outbreak" in label.lower() for label in STATUS_LABELS.values())
