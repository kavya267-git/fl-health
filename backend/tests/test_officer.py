"""Health officer views: background ensemble, situation report, exports with the watermark, alerts, populations."""

import io
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from analytics.forecasting.live_ensemble import LiveEnsembleConfig, run_live_ensemble
from analytics.forecasting.lstm import LSTMSettings
from analytics.geospatial.regions import apply_populations, load_regions
from app.analytics.ensemble_service import EnsembleService
from app.main import create_app
from backend_test_helpers import login

WATERMARK = "SIMULATED DATA – NOT REAL CASES"
NORTH = ["R01", "R02", "R03", "R04", "R05", "R06"]
BOUNDARIES = Path(__file__).resolve().parents[2] / "data" / "boundaries"
#: Small members so a full run takes seconds in tests; the protocol is the same as the real configuration.
FAST = LiveEnsembleConfig(members=("naive", "seasonal_naive", "arima_least_squares"))


def make_fast(ctx):
    ctx.ensemble.config = FAST


# ------------------------------------------------------------------ live ensemble core
def synthetic(n_series=6, weeks=80, seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(weeks)
    series = {f"d:R{k}": list(np.round(30 + 10 * np.sin(2 * np.pi * t / 52 + k) + rng.normal(0, 3, weeks))) for k in range(n_series)}
    series["d:sparse"] = [None if i % 3 else 5.0 for i in range(weeks)]  # two thirds missing
    names = [f"2025-W{i:03d}" for i in range(weeks)]
    return series, names


def test_live_ensemble_follows_the_fixed_rules():
    series, weeks = synthetic()
    config = LiveEnsembleConfig(members=("naive", "seasonal_naive", "lstm"), lstm=LSTMSettings(epochs=2, hidden=8))
    result = run_live_ensemble(series, weeks, config)
    assert result["validation_window"] == {"first_week": weeks[-20], "last_week": weeks[-1], "weeks": 20}
    assert result["data_through"] == weeks[-1]
    for h in "1234":
        w = result["weights"][h]
        assert all(v >= 0 for v in w.values()) and sum(w.values()) == pytest.approx(1.0)
    assert "d:sparse" in result["excluded"] and "missing" in result["excluded"]["d:sparse"]
    for points in result["forecasts"].values():
        assert [p["horizon"] for p in points] == [1, 2, 3, 4]
        assert all(0 <= p["lower"] <= p["upper"] and p["predicted"] >= 0 for p in points)


def test_ensemble_run_is_stored_and_reused_after_a_restart(ctx):
    make_fast(ctx)
    assert ctx.ensemble.latest() is None and ctx.ensemble.needs_run()
    run = ctx.ensemble.run()
    assert run is not None and run["forecasts"]
    assert not ctx.ensemble.needs_run()
    # A new service over the same database (as after a restart) finds the stored run without training.
    restarted = EnsembleService(ctx.db, ctx.surveillance, FAST)
    assert restarted.latest()["run_id"] == run["run_id"] and not restarted.needs_run()
    assert ctx.db.fetch_one("SELECT COUNT(*) AS n FROM ensemble_runs")["n"] == 1


def test_a_failed_run_is_recorded_and_not_used(ctx):
    ctx.ensemble.config = LiveEnsembleConfig(members=("no-such-model",))
    assert ctx.ensemble.run() is None
    assert ctx.ensemble.latest() is None
    assert ctx.ensemble.status()["last_error"]


# ------------------------------------------------------------------ situation report
@pytest.fixture
def app_client(settings):
    with TestClient(create_app(settings)) as client:
        make_fast(client.app.state.ctx)
        yield client


def test_situation_report_before_the_forecast_is_ready_says_so(app_client):
    officer = login(app_client, "officer_north@fl-healthcare.demo")
    report = app_client.get("/api/officer/situation", headers=officer).json()
    assert report["about_forecast"]["available"] is False
    region = report["diseases"][0]["regions"][0]
    assert region["forecast"] == {"available": False, "reason": "The forecast is still being computed."}


def test_situation_report_is_scoped_and_complete(app_client):
    app_client.app.state.ctx.ensemble.run()
    north = login(app_client, "officer_north@fl-healthcare.demo")
    report = app_client.get("/api/officer/situation", headers=north).json()
    assert report["jurisdiction"] == NORTH
    assert report["data_status"]["watermark"] == WATERMARK
    about = report["about_forecast"]
    assert about["available"] and about["validation_window"]["weeks"] == 20
    assert about["data_through"] == report["diseases"][0]["week"]["week_start"]
    assert all(sum(w.values()) == pytest.approx(1.0) for w in about["weights"].values())
    for block in report["diseases"]:
        assert sorted(r["region_id"] for r in block["regions"]) == NORTH
        for r in block["regions"]:
            assert 0 <= r["reporting_hospitals"] <= r["expected_hospitals"] <= 4
            if r["case_count"] is not None and r["usual_level"]:
                assert r["ratio_to_usual"] == pytest.approx(r["case_count"] / r["usual_level"])
            if r["forecast"]["available"]:
                s = r["forecast"]["summary"]
                assert s["horizons"] == [2, 3, 4] and s["range_low"] <= s["predicted_low"] <= s["predicted_high"] <= s["range_high"]
            else:
                assert r["forecast"]["reason"].startswith("No forecast")


def test_viewers_researchers_and_hospital_roles_get_no_situation_report(app_client):
    for email in ("viewer@fl-healthcare.demo", "researcher@fl-healthcare.demo", "manager_a@fl-healthcare.demo"):
        assert app_client.get("/api/officer/situation", headers=login(app_client, email)).status_code == 403


# ------------------------------------------------------------------ exports
def test_csv_export_is_stamped_on_top_and_in_every_row_and_audited(app_client):
    north = login(app_client, "officer_north@fl-healthcare.demo")
    response = app_client.get("/api/officer/situation.csv", headers=north)
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/csv")
    assert "SIMULATED-situation-report.csv" in response.headers["content-disposition"]
    lines = response.text.splitlines()
    assert lines[0] == f"# {WATERMARK}"
    data = [line for line in lines if not line.startswith("#")]
    assert data[0].startswith("data_flag,")
    assert len(data) == 1 + 3 * len(NORTH) and all(line.startswith(WATERMARK + ",") for line in data[1:])
    admin = login(app_client, "admin@fl-healthcare.demo")
    audit = app_client.get("/api/audit", params={"action": "SITUATION_REPORT_EXPORTED"}, headers=admin).json()["items"]
    assert audit and audit[0]["details"]["format"] == "csv" and audit[0]["details"]["simulated"] is True


def test_pdf_export_carries_the_watermark_on_every_page(app_client):
    from pypdf import PdfReader

    north = login(app_client, "officer_north@fl-healthcare.demo")
    response = app_client.get("/api/officer/situation.pdf", headers=north)
    assert response.status_code == 200 and response.content.startswith(b"%PDF")
    pages = PdfReader(io.BytesIO(response.content)).pages
    assert len(pages) >= 1
    for page in pages:
        assert WATERMARK in page.extract_text()


# ------------------------------------------------------------------ alerts
def test_alerts_are_created_when_a_region_becomes_a_potential_hotspot(ctx):
    alerts = ctx.alerts.list()
    assert alerts, "the simulated data injects rises, so some alerts are expected"
    assert all(a["state"] == "OPEN" and a["is_simulated"] for a in alerts)
    assert ctx.alerts.sync() == 0  # nothing new for unchanged data
    keys = {(a["region_id"], a["disease"], a["week_start"]) for a in alerts}
    assert len(keys) == len(alerts)


def test_alert_workflow_is_scoped_ordered_and_audited(client, admin):
    north = login(client, "officer_north@fl-healthcare.demo")
    south = login(client, "officer_south@fl-healthcare.demo")
    mine = client.get("/api/alerts", headers=north).json()
    assert mine and all(a["region_id"] in NORTH for a in mine)
    alert = mine[0]
    url = f"/api/alerts/{alert['id']}"

    hidden = client.post(f"{url}/acknowledge", headers=south)  # outside the south jurisdiction
    assert hidden.status_code == 404 and hidden.json()["detail"] == "No such alert."
    early = client.post(f"{url}/outcome", headers=north, json={"outcome": "CONFIRMED", "note": "Checked"})
    assert early.status_code == 409  # acknowledge first
    acknowledged = client.post(f"{url}/acknowledge", headers=north).json()
    assert acknowledged["state"] == "ACKNOWLEDGED" and acknowledged["acknowledged_by"] == "officer_north@fl-healthcare.demo"
    assert client.post(f"{url}/acknowledge", headers=north).status_code == 409
    assert client.post(f"{url}/outcome", headers=north, json={"outcome": "MAYBE", "note": "x"}).status_code == 422
    closed = client.post(f"{url}/outcome", headers=north, json={"outcome": "REPORTING_ARTEFACT", "note": "Late batch upload"})
    assert closed.json()["state"] == "CLOSED" and closed.json()["outcome_label"] == "Reporting artefact"
    again = client.post(f"{url}/outcome", headers=north, json={"outcome": "CONFIRMED", "note": "x"})
    assert again.status_code == 409

    actions = {
        action
        for action in ("ALERT_CREATED", "ALERT_ACKNOWLEDGED", "ALERT_OUTCOME_RECORDED")
        for e in client.get("/api/audit", params={"action": action, "limit": 200}, headers=admin).json()["items"]
        if e["details"].get("alert_id") == alert["id"]
    }
    assert {"ALERT_CREATED", "ALERT_ACKNOWLEDGED", "ALERT_OUTCOME_RECORDED"} <= set(actions)


def test_hotspot_precision_counts_only_health_officer_outcomes(ctx):
    everywhere = [r["region_id"] for r in ctx.surveillance.regions()]
    officer = {"email": "officer_north@fl-healthcare.demo", "role": "health_officer", "jurisdiction": everywhere}
    admin = {"email": "admin@fl-healthcare.demo", "role": "admin"}
    alerts = ctx.alerts.list()[:4]
    for alert, outcome in zip(alerts[:3], ("CONFIRMED", "NOT_CONFIRMED", "REPORTING_ARTEFACT")):
        ctx.alerts.acknowledge(alert["id"], officer)
        ctx.alerts.record_outcome(alert["id"], officer, outcome, "demo")
    ctx.alerts.acknowledge(alerts[3]["id"], admin)
    ctx.alerts.record_outcome(alerts[3]["id"], admin, "CONFIRMED", "recorded by an administrator")
    result = ctx.alerts.precision()
    assert result["real"]["outcomes"] == 0 and result["real"]["precision"] is None
    demo = result["demo"]
    assert demo["outcomes"] == 3 and demo["confirmed"] == 1  # the administrator's outcome is not counted
    assert demo["precision"] == pytest.approx(1 / 3) and demo["precision_excluding_artefacts"] == pytest.approx(1 / 2)
    assert result["demo_by_others"]["outcomes"] == 1 and result["demo_by_others"]["confirmed"] == 1


def test_alerts_outside_the_jurisdiction_look_like_unknown_ids(client):
    north = login(client, "officer_north@fl-healthcare.demo")
    south = login(client, "officer_south@fl-healthcare.demo")
    theirs = client.get("/api/alerts", headers=south).json()[0]
    for path, body in (("acknowledge", None), ("outcome", {"outcome": "CONFIRMED", "note": "x"})):
        outside = client.post(f"/api/alerts/{theirs['id']}/{path}", headers=north, json=body)
        unknown = client.post(f"/api/alerts/99999999/{path}", headers=north, json=body)
        assert outside.status_code == unknown.status_code == 404
        assert outside.json() == unknown.json() == {"detail": "No such alert."}
        assert theirs["region_id"] not in outside.text


def test_concurrent_alert_syncs_never_raise_or_duplicate(ctx):
    import threading

    before = ctx.db.fetch_one("SELECT COUNT(*) AS n FROM alerts")["n"]
    alert = ctx.alerts.list()[0]
    region = {"region_id": alert["region_id"], "case_count": 1, "baseline_mean": 1.0}
    assert ctx.alerts._create(alert["disease"], region, alert["week_start"], True) == 0  # already there: ignored

    ctx.db.execute("DELETE FROM alerts")
    ctx.alerts._synced_version = None
    errors = []

    def sync():
        try:
            ctx.alerts._synced_version = None
            ctx.alerts.sync()
        except Exception as exc:  # pragma: no cover - the assertion below reports it
            errors.append(exc)

    threads = [threading.Thread(target=sync) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert ctx.db.fetch_one("SELECT COUNT(*) AS n FROM alerts")["n"] == before


def test_internal_recomputation_writes_no_analytics_audit_but_user_requests_do(ctx):
    entries = ctx.audit.list_entries(None, "ANALYTICS_GENERATED", None, None, None, None, None, 200, 0)["items"]
    assert entries == []  # bootstrap ran the alert sync over 13 weeks x 3 diseases without auditing it
    assert ctx.audit.list_entries(None, "ALERT_CREATED", None, None, None, None, None, 200, 0)["items"]

    ctx.surveillance.hotspots("dengue", None, "viewer@example.org")  # cached by the sync, first served to a user
    ctx.surveillance.hotspots("dengue", None, "viewer@example.org")  # already audited for users
    entries = ctx.audit.list_entries(None, "ANALYTICS_GENERATED", None, None, None, None, None, 200, 0)["items"]
    assert [e["actor"] for e in entries] == ["viewer@example.org"]


def test_background_job_limits_pytorch_threads_and_restores_them(ctx, monkeypatch):
    import torch

    from app.analytics import ensemble_service

    seen = {}

    def fake_run(series, weeks, config, progress):
        seen["threads"] = torch.get_num_threads()
        raise RuntimeError("stop after recording")

    monkeypatch.setattr(ensemble_service, "run_live_ensemble", fake_run)
    before = torch.get_num_threads()
    ctx.ensemble.run(torch_threads=2)
    assert seen["threads"] == 2
    assert torch.get_num_threads() == before


# ------------------------------------------------------------------ Census 2011 populations
def test_census_2011_populations_match_the_districts_and_the_state_total():
    collection = load_regions(BOUNDARIES / "karnataka_districts.geojson")
    matched = apply_populations(collection, BOUNDARIES / "karnataka_census2011_population.csv")
    assert matched == 30
    assert sum(f["properties"]["population"] for f in collection["features"]) == 61_095_297  # Karnataka, 2011


def test_rates_per_100k_are_labelled_census_2011(settings):
    settings = settings.model_copy(
        update={
            "regions_geojson_path": BOUNDARIES / "karnataka_districts.geojson",
            "region_populations_csv": BOUNDARIES / "karnataka_census2011_population.csv",
        }
    )
    with TestClient(create_app(settings)) as client:
        viewer = login(client, "viewer@fl-healthcare.demo")
        hotspots = client.get("/api/analytics/hotspots", params={"disease": "dengue"}, headers=viewer).json()
        assert hotspots["data_status"]["population_source"] == "Census 2011 population (30 of 30 regions)"
        assert any(r["case_rate"] is not None for r in hotspots["regions"])
