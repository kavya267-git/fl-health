"""Bed projection arithmetic, checked against hand calculations (the same example is in docs/resource-planning.md)."""

import pytest

from analytics.planning.projection import DiseaseAssumptions, beds_occupied, hospital_share, project, weekly_admissions


def test_share_uses_only_weeks_with_both_counts_known():
    # Weeks 2 and 3 each miss one count, so only weeks 1 and 4 count: (10 + 30) / (40 + 60) = 0.4.
    assert hospital_share([10, None, 20, 30], [40, 50, None, 60]) == pytest.approx(0.4)


def test_share_looks_back_8_weeks_only():
    # The first two weeks fall outside the last 8; the remaining 8 are 5 of 10 each.
    assert hospital_share([100, 100] + [5] * 8, [100, 100] + [10] * 8) == pytest.approx(0.5)


def test_share_is_missing_rather_than_guessed():
    assert hospital_share([None, None], [10, 20]) is None
    assert hospital_share([0, 0], [0, 0]) is None


def test_admissions_sum_regions_times_share_times_admission_rate():
    # Week 1: (100 x 0.4 + 50 x 0.2) x 0.1 = 5.0; week 2: (200 x 0.4 + 50 x 0.2) x 0.1 = 9.0.
    result = weekly_admissions({"A": [100, 200], "B": [50, 50]}, {"A": 0.4, "B": 0.2}, 0.1)
    assert result == pytest.approx([5.0, 9.0])


def test_beds_carry_over_into_the_next_week():
    # Stay 10 days, arriving at the start of the week: 7 of the 10 days in the first week, 3 in the next.
    # Week 1: 7 x 7/7 = 7. Week 2: 7 x 3/7 + 14 x 7/7 = 17. Week 3: 14 x 3/7 + 0 = 6.
    assert beds_occupied([7, 14, 0], 10) == pytest.approx([7, 17, 6])


def test_short_stays_fill_part_of_a_week():
    # 14 patients staying 3.5 days fill 14 x 3.5 / 7 = 7 beds on average that week, and none the next.
    assert beds_occupied([14, 0], 3.5) == pytest.approx([7, 0])


def test_long_stays_carry_over_several_weeks():
    # 7 patients staying 15 days: 7 days in week 1, 7 in week 2, 1 in week 3 -> 7, 7, 1 beds.
    assert beds_occupied([7, 0, 0], 15) == pytest.approx([7, 7, 1])


def test_worked_example():
    """Region forecast for weeks 1-4 (low / central / high), share 0.25, 20% admitted, 10% of them in ICU,
    10-day stays, 40 beds at 75% occupancy (30 beds in use today)."""
    forecasts = {"A": {"low": [80, 90, 100, 70], "mid": [100, 120, 140, 100], "high": [130, 160, 190, 140]}}
    result = project(forecasts, {"A": 0.25}, DiseaseAssumptions(0.2, 0.1, 10), current_occupied=30)
    # Admissions = forecast x 0.25 x 0.2 = forecast x 0.05.
    assert result["admissions_mid"] == pytest.approx([5, 6, 7, 5])
    assert result["admissions_high"] == pytest.approx([6.5, 8, 9.5, 7])
    # Beds in week t = admissions in t + admissions in t-1 x 3/7.
    assert result["beds_mid"] == pytest.approx([5, 6 + 5 * 3 / 7, 7 + 6 * 3 / 7, 5 + 7 * 3 / 7])
    assert result["beds_high"] == pytest.approx([6.5, 8 + 6.5 * 3 / 7, 9.5 + 8 * 3 / 7, 7 + 9.5 * 3 / 7])
    assert result["beds_low"] == pytest.approx([4, 4.5 + 4 * 3 / 7, 5 + 4.5 * 3 / 7, 3.5 + 5 * 3 / 7])
    # Totals add today's 30 beds: high = 36.5, 40.79, 42.93, 41.07 (above 40 in weeks 2-4).
    assert result["total_beds_high"] == pytest.approx([36.5, 40.785714, 42.928571, 41.071429], abs=1e-5)
    assert [t > 40 for t in result["total_beds_high"]] == [False, True, True, True]
    # ICU beds = 10% of the bed numbers (same stay length).
    assert result["icu_beds_high"] == pytest.approx([b * 0.1 for b in result["beds_high"]])
