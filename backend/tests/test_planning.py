"""Resource planning: capacity form, admin assumptions, the projection's inputs and wording rules, and scope."""

import pytest

from analytics.planning.projection import DiseaseAssumptions, hospital_share, project
from app.analytics.planning_service import ASSUMED_LABEL, group_weeks
from app.utils.time import utc_now_iso
from backend_test_helpers import login

MANAGER = "manager_a@fl-healthcare.demo"


def store_forecast(ctx, value=100.0, low=80.0, high=130.0):
    """Store an ensemble run whose forecast is the same known numbers for every region and disease."""
    weeks = ctx.surveillance.regional_series(ctx.surveillance.diseases()[0]["id"])["weeks"]
    points = [{"horizon": h, "predicted": value, "lower": low, "upper": high} for h in range(1, 5)]
    forecasts = {
        f"{d['id']}:{r['region_id']}": points for d in ctx.surveillance.diseases() for r in ctx.surveillance.regions()
    }
    ctx.db.insert(
        "ensemble_runs",
        {
            "data_version": ctx.surveillance._data_version(),
            "status": "DONE",
            "started_at": utc_now_iso(),
            "finished_at": utc_now_iso(),
            "is_simulated": True,
            "payload": {
                "forecasts": forecasts,
                "excluded": {},
                "data_through": weeks[-1],
                "level": 0.8,
                "members": ["naive"],
                "member_labels": {"naive": "Naive"},
                "weights": {},
                "validation": {},
                "validation_window": {"first_week": weeks[-20], "last_week": weeks[-1], "weeks": 20},
            },
        },
    )


# ------------------------------------------------------------------ assumptions
def test_default_assumptions_are_labelled_as_assumed_and_admins_replace_them(client, admin):
    manager = login(client, MANAGER)
    rows = client.get("/api/planning/assumptions", headers=manager).json()
    assert {r["disease"] for r in rows} == {"dengue", "influenza_like_illness", "acute_gastroenteritis"}
    assert all(r["is_default"] and r["label"] == ASSUMED_LABEL for r in rows)
    assert ASSUMED_LABEL == "Assumed values, replace with local figures"

    body = {"admission_rate": 0.3, "icu_share": 0.1, "length_of_stay_days": 6}
    assert client.post("/api/planning/assumptions/dengue", headers=manager, json=body).status_code == 403
    changed = client.post("/api/planning/assumptions/dengue", headers=admin, json=body).json()
    assert changed["is_default"] is False and changed["label"] == "Set by an administrator"
    assert changed["admission_rate"] == 0.3 and changed["updated_by"] == "admin@fl-healthcare.demo"
    bad = {"admission_rate": 1.5, "icu_share": 0.1, "length_of_stay_days": 6}
    assert client.post("/api/planning/assumptions/dengue", headers=admin, json=bad).status_code == 422
    audit = client.get("/api/audit", params={"action": "PLANNING_ASSUMPTIONS_CHANGED"}, headers=admin).json()["items"]
    assert audit and audit[0]["details"]["to"]["admission_rate"] == 0.3


def test_defaults_never_overwrite_admin_values_on_restart(ctx):
    ctx.planning.set_assumptions("dengue", {"admission_rate": 0.5, "icu_share": 0.2, "length_of_stay_days": 7}, "admin")
    ctx.planning.seed_assumptions()
    dengue = next(a for a in ctx.planning.assumptions() if a["disease"] == "dengue")
    assert dengue["admission_rate"] == 0.5 and not dengue["is_default"]


# ------------------------------------------------------------------ capacity
def test_capacity_is_stored_with_a_timestamp_kept_as_history_and_audited(client, admin):
    manager = login(client, MANAGER)
    first = client.post("/api/planning/capacity", headers=manager, json={"total_beds": 40, "icu_beds": 4, "occupancy_percent": 75})
    assert first.status_code == 200 and first.json()["hospital_id"] == "hospital_a" and first.json()["entered_at"]
    client.post("/api/planning/capacity", headers=manager, json={"total_beds": 42, "icu_beds": 4, "occupancy_percent": 80})
    history = client.get("/api/planning/capacity/history", headers=manager).json()
    assert [h["total_beds"] for h in history] == [42, 40]  # newest first, nothing overwritten
    entries = client.get("/api/audit", params={"action": "HOSPITAL_CAPACITY_CHANGED"}, headers=admin).json()["items"]
    assert entries[0]["hospital_id"] == "hospital_a"
    assert entries[0]["details"]["from"]["total_beds"] == 40 and entries[0]["details"]["to"]["total_beds"] == 42


def test_capacity_is_validated(client):
    manager = login(client, MANAGER)
    for body in (
        {"total_beds": 10, "icu_beds": 11, "occupancy_percent": 50},  # more ICU beds than beds
        {"total_beds": 10, "icu_beds": 1, "occupancy_percent": 120},
        {"total_beds": 0, "icu_beds": 0, "occupancy_percent": 10},
    ):
        assert client.post("/api/planning/capacity", headers=manager, json=body).status_code == 422


def test_managers_see_only_their_own_hospital_and_admins_must_choose_one(client, admin):
    manager = login(client, MANAGER)
    assert client.get("/api/planning", params={"hospital_id": "hospital_b"}, headers=manager).status_code == 403
    assert client.get("/api/planning", headers=admin).status_code == 422
    assert client.get("/api/planning", params={"hospital_id": "hospital_b"}, headers=admin).status_code == 200
    for email in ("hospital_a@fl-healthcare.demo", "officer_north@fl-healthcare.demo", "viewer@fl-healthcare.demo"):
        assert client.get("/api/planning", headers=login(client, email)).status_code == 403


# ------------------------------------------------------------------ projection
def test_projection_says_what_is_missing_before_it_can_be_computed(ctx):
    first = ctx.planning.projection("hospital_a")
    assert first["available"] is False and "Enter your hospital" in first["reason"]
    ctx.planning.set_capacity("hospital_a", 40, 4, 75, "manager")
    second = ctx.planning.projection("hospital_a")
    assert second["available"] is False and "still being computed" in second["reason"]
    assert second["label"] == "Planning estimate"


def test_projection_uses_the_hospital_share_forecast_and_assumptions(ctx):
    ctx.planning.set_capacity("hospital_a", 40, 4, 75, "manager")
    store_forecast(ctx)
    result = ctx.planning.projection("hospital_a")
    assert result["available"] and result["current_beds_occupied"] == pytest.approx(30)
    assert result["data_status"]["simulated"] is True

    dengue = next(d for d in result["diseases"] if d["disease"]["id"] == "dengue")
    regional = ctx.surveillance.regional_series("dengue")
    # Recompute every region's share straight from the stored reports and compare.
    expected = {}
    for region in dengue["regions"]:
        rows = ctx.db.fetch_all(
            "SELECT week_start, case_count, suppressed FROM surveillance_reports "
            "WHERE hospital_id = 'hospital_a' AND disease = 'dengue' AND region_id = :r",
            {"r": region["region_id"]},
        )
        by_week = {str(r["week_start"]): (None if r["suppressed"] else r["case_count"]) for r in rows}
        mine = [by_week.get(w) for w in regional["weeks"]]
        expected[region["region_id"]] = hospital_share(mine, regional["counts"][region["region_id"]])
        assert region["share"] == pytest.approx(expected[region["region_id"]])
    assert dengue["regions"], "hospital_a reports dengue for at least one region"

    # Every region's forecast is 100 (80-130), so admissions = 100 x (sum of shares) x admission rate.
    rate = dengue["assumptions"]["admission_rate"]
    total_share = sum(expected.values())
    week1 = dengue["weeks"][0]
    assert week1["admissions_mid"] == pytest.approx(100 * total_share * rate)
    assert week1["admissions_high"] == pytest.approx(130 * total_share * rate)
    # And the whole projection equals the plain arithmetic on those inputs.
    reference = project(
        {r: {"low": [80] * 4, "mid": [100] * 4, "high": [130] * 4} for r in expected},
        expected,
        DiseaseAssumptions(rate, dengue["assumptions"]["icu_share"], dengue["assumptions"]["length_of_stay_days"]),
        30,
    )
    assert [w["total_beds_high"] for w in dengue["weeks"]] == pytest.approx(reference["total_beds_high"])
    assert [w["over_capacity"] for w in dengue["weeks"]] == [t > 40 for t in reference["total_beds_high"]]

    # All diseases together: the beds add up.
    combined = result["all_diseases"]
    available = [d for d in result["diseases"] if d["available"]]
    assert combined[0]["beds_high"] == pytest.approx(sum(d["weeks"][0]["beds_high"] for d in available))


def test_weeks_are_grouped_for_plain_sentences():
    """The worked example: weeks 2-4 may exceed 40 beds; their range is 35.6 to 42.9 beds in total."""
    forecasts = {"A": {"low": [80, 90, 100, 70], "mid": [100, 120, 140, 100], "high": [130, 160, 190, 140]}}
    result = project(forecasts, {"A": 0.25}, DiseaseAssumptions(0.2, 0.1, 10), 30)
    weeks = [
        {"horizon": i + 1, **{k: v[i] for k, v in result.items()}, "over_capacity": result["total_beds_high"][i] > 40}
        for i in range(4)
    ]
    groups = group_weeks(weeks)
    assert [(g["first_week"], g["last_week"], g["over_capacity"]) for g in groups] == [(1, 1, False), (2, 4, True)]
    assert groups[1]["total_low"] == pytest.approx(30 + 3.5 + 5 * 3 / 7)  # 35.64, week 4's low
    assert groups[1]["total_high"] == pytest.approx(30 + 9.5 + 8 * 3 / 7)  # 42.93, week 3's high
    assert groups[0]["total_low"] == pytest.approx(34) and groups[0]["total_high"] == pytest.approx(36.5)


# ------------------------------------------------------------------ fixed demo week
def test_simulation_end_week_pins_the_simulated_data(settings, monkeypatch):
    from datetime import date

    from app.config import load_settings
    from app.services.context import bootstrap, build_context

    pinned = settings.model_copy(update={"simulation_end_week": date(2026, 9, 7)})
    ctx = build_context(pinned)
    try:
        bootstrap(ctx)
        weeks = ctx.surveillance.regional_series("dengue")["weeks"]
        assert weeks[-1] == "2026-09-07" and len(weeks) == pinned.surveillance_weeks
    finally:
        ctx.close()

    monkeypatch.setenv("SIMULATION_END_WEEK", "2026-11-02")
    assert load_settings().simulation_end_week == date(2026, 11, 2)
    monkeypatch.setenv("SIMULATION_END_WEEK", "2026-11-03")  # a Tuesday
    with pytest.raises(ValueError, match="must be a Monday"):
        load_settings()
    monkeypatch.delenv("SIMULATION_END_WEEK")
    assert load_settings().simulation_end_week is None  # rolling by default


def _home_ctx(settings, homes):
    from app.services.context import bootstrap, build_context

    context = build_context(settings.model_copy(update={"demo_hospital_regions": homes}))
    bootstrap(context)
    return context


def test_with_home_districts_a_hospital_plans_for_its_own_district_only(settings):
    context = _home_ctx(settings, {})
    try:
        regions_by_id = sorted(r["region_id"] for r in context.surveillance.regions())
    finally:
        context.close()
    homes = {"hospital_a": regions_by_id[0], "hospital_b": regions_by_id[5]}
    ctx = _home_ctx(settings, homes)
    try:
        ctx.planning.set_capacity("hospital_a", 40, 4, 75, "manager")
        store_forecast(ctx)
        result = ctx.planning.projection("hospital_a")
        assert result["catchment"]["basis"] == "home_district" and result["catchment"]["share"] == 1.0
        for disease in result["diseases"]:
            assert [(r["region_id"], r["share"]) for r in disease["regions"]] == [(regions_by_id[0], 1.0)]
        dengue = next(d for d in result["diseases"] if d["disease"]["id"] == "dengue")
        rate = dengue["assumptions"]["admission_rate"]
        assert dengue["weeks"][0]["admissions_mid"] == pytest.approx(100 * 1.0 * rate)
        # A hospital without a configured home district still uses its share of the reports.
        ctx.planning.set_capacity("hospital_c", 40, 4, 75, "manager")
        assert ctx.planning.projection("hospital_c")["catchment"]["basis"] == "reports"
    finally:
        ctx.close()


def test_hospitals_sharing_a_home_district_split_it(settings):
    context = _home_ctx(settings, {})
    try:
        first = sorted(r["region_id"] for r in context.surveillance.regions())[0]
    finally:
        context.close()
    ctx = _home_ctx(settings, {"hospital_a": first, "hospital_b": first})
    try:
        ctx.planning.set_capacity("hospital_a", 40, 4, 75, "manager")
        store_forecast(ctx)
        result = ctx.planning.projection("hospital_a")
        assert result["catchment"]["share"] == 0.5 and result["catchment"]["hospitals_sharing"] == 2
    finally:
        ctx.close()
