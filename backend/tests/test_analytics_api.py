"""Analytics endpoints: overview, hotspots, forecast, explainability, privacy."""

from backend_test_helpers import login, wait_for_round


def test_overview_before_any_round(client, viewer):
    overview = client.get("/api/analytics/overview", headers=viewer).json()
    kpis = overview["kpis"]
    assert kpis["participating_hospitals"] == 4 and kpis["modalities"] == 3
    assert kpis["fl_rounds_total"] == 0 and kpis["models_trained"] == 0
    assert all(model["metrics"] is None for model in overview["models"])
    assert overview["data_status"]["simulated"] is True
    assert overview["surveillance"]["available"] is True
    assert "not a confirmed outbreak" in overview["surveillance"]["disclaimer"]


def test_overview_includes_audit_activity_only_for_roles_that_may_read_the_audit_log(client, viewer, coordinator, admin):
    operator = login(client, "hospital_a@fl-healthcare.demo")
    for headers in (viewer, operator):
        assert client.get("/api/audit", headers=headers).status_code == 403
        assert client.get("/api/analytics/overview", headers=headers).json()["recent_activity"] is None
    for headers in (coordinator, admin):
        assert client.get("/api/audit", headers=headers).status_code == 200
        activity = client.get("/api/analytics/overview", headers=headers).json()["recent_activity"]
        assert isinstance(activity, list) and activity  # signing in is itself audited


def test_options_and_hotspots(client, viewer):
    options = client.get("/api/analytics/options", headers=viewer).json()
    assert len(options["regions"]) == 12 and len(options["diseases"]) == 3
    assert options["periods"][0] == options["latest_period"]
    assert options["data_status"]["simulated"] is True

    hotspots = client.get("/api/analytics/hotspots", params={"disease": "dengue"}, headers=viewer).json()
    assert hotspots["disease"]["id"] == "dengue"
    assert len(hotspots["regions"]) == 12 == len(hotspots["geojson"]["features"])
    assert sum(hotspots["summary"].values()) == 12
    allowed = {"NORMAL", "ELEVATED", "CANDIDATE_HOTSPOT", "INSUFFICIENT_DATA"}
    for region in hotspots["regions"]:
        assert region["status"] in allowed
        assert region["hotspot_flag"] == (region["status"] == "CANDIDATE_HOTSPOT")
        for key in ("region_id", "disease", "time_period", "case_count", "case_rate", "anomaly_score"):
            assert key in region
        if region["case_count"] is not None and region["population"]:
            assert abs(region["case_rate"] - region["case_count"] / region["population"] * 1e5) < 1e-6
    labels = {r["status_label"] for r in hotspots["regions"]}
    assert "Outbreak" not in " ".join(labels)
    assert hotspots["summary"]["CANDIDATE_HOTSPOT"] >= 1  # the simulation injects a rise
    assert hotspots["method"]["method"].startswith("Historical z-score")

    earlier = options["periods"][5]["week_start"]
    past = client.get("/api/analytics/hotspots", params={"disease": "dengue", "period": earlier}, headers=viewer).json()
    assert past["time_period"]["week_start"] == earlier
    assert client.get("/api/analytics/hotspots", params={"disease": "plague"}, headers=viewer).status_code == 404
    assert client.get("/api/analytics/hotspots", params={"period": "1999-01-04"}, headers=viewer).status_code == 422


def test_forecast(client, viewer):
    options = client.get("/api/analytics/options", headers=viewer).json()
    region_id = max(options["regions"], key=lambda r: r["population"])["region_id"]
    forecast = client.get(
        "/api/analytics/forecast",
        params={"region_id": region_id, "disease": "influenza_like_illness", "horizon": 6},
        headers=viewer,
    ).json()
    assert forecast["available"] is True
    assert forecast["forecast_horizon"] == 6 and len(forecast["predicted_values"]) == 6 == len(forecast["forecast"])
    assert forecast["model_name"]
    metrics = forecast["evaluation_metrics"]
    assert metrics["mae"] >= 0 and metrics["rmse"] >= metrics["mae"] - 1e-9
    assert "Chronological" in metrics["split"]
    for point in forecast["forecast"]:
        assert point["lower_95"] <= point["lower_80"] <= point["predicted"] <= point["upper_80"] <= point["upper_95"]
        assert point["week_start"] > forecast["data_through"]
    assert any(candidate["selected"] for candidate in forecast["candidates"])
    assert "not confirmed future cases" in forecast["disclaimer"]
    assert client.get("/api/analytics/forecast", params={"horizon": 99}, headers=viewer).status_code == 422
    assert client.get("/api/analytics/forecast", params={"region_id": "R99"}, headers=viewer).status_code == 404


def test_explainability_is_unavailable_until_a_model_is_trained(client, viewer):
    for modality in ("ehr", "ecg", "xray"):
        body = client.get("/api/analytics/explainability", params={"modality": modality}, headers=viewer).json()
        assert body["available"] is False and body["explanation"] is None
        assert "not been trained" in body["reason"]
        assert body["cases"] and all(case["synthetic"] for case in body["cases"])


def test_explainability_after_training(client, coordinator):
    for modality in ("ehr", "ecg", "xray"):
        round_id = client.post("/api/federated/rounds/start", json={"modality": modality}, headers=coordinator).json()[
            "id"
        ]
        assert wait_for_round(client, coordinator, round_id)["status"] == "COMPLETED"

    ehr = client.get(
        "/api/analytics/explainability", params={"modality": "ehr", "scope": "individual"}, headers=coordinator
    ).json()
    assert ehr["available"] is True
    explanation = ehr["explanation"]
    assert explanation["scope"] == "individual" and "Shapley" in explanation["method"]
    assert len(explanation["contributions"]) == 14
    total = explanation["base_value"] + sum(c["shap_value"] for c in explanation["contributions"])
    assert abs(total - explanation["additivity"]["model_output"]) < 1e-6

    global_view = client.get(
        "/api/analytics/explainability", params={"modality": "ehr", "scope": "global"}, headers=coordinator
    ).json()
    assert global_view["available"] is True and global_view["explanation"]["scope"] == "global"
    assert len(global_view["explanation"]["features"]) == 14
    assert global_view["explanation"]["metadata"]["hospitals_contributing"] == 4

    ecg = client.get("/api/analytics/explainability", params={"modality": "ecg"}, headers=coordinator).json()
    assert ecg["available"] and len(ecg["explanation"]["signal"]) == 187 == len(ecg["explanation"]["importance"])
    ecg_global = client.get(
        "/api/analytics/explainability", params={"modality": "ecg", "scope": "global"}, headers=coordinator
    ).json()
    assert ecg_global["available"] is False and ecg_global["reason"]

    xray = client.get("/api/analytics/explainability", params={"modality": "xray"}, headers=coordinator).json()
    assert xray["available"] and len(xray["explanation"]["heatmap"]) == 64
    assert xray["explanation"]["image_png_base64"]
    assert (
        client.get(
            "/api/analytics/explainability", params={"modality": "ehr", "case_id": "nope"}, headers=coordinator
        ).status_code
        == 404
    )


def test_privacy_report(client, coordinator):
    report = client.get("/api/analytics/privacy", headers=coordinator).json()
    assert "does not by itself guarantee privacy" in report["statement"]
    checks = {check["id"]: check["status"] for check in report["checks"]}
    assert checks["central_schema"] == "PASS" and checks["storage_separation"] == "PASS"
    assert checks["small_cells"] == "PASS"
    assert report["differential_privacy"]["prototype"] is True

    round_id = client.post(
        "/api/federated/rounds/start",
        json={"modality": "ehr", "differential_privacy": {"enabled": True, "clip_norm": 1.0, "noise_multiplier": 0.5}},
        headers=coordinator,
    ).json()["id"]
    assert wait_for_round(client, coordinator, round_id)["status"] == "COMPLETED"
    report = client.get("/api/analytics/privacy", headers=coordinator).json()
    accounting = report["differential_privacy"]["accounting"]
    assert len(accounting) == 4
    assert all(entry["rounds_with_dp"] == 1 and entry["bound_covers_all_rounds"] for entry in accounting)
    assert all(entry["epsilon_over_dp_rounds"] > 0 for entry in accounting)


def test_analytics_events_are_audited(client, coordinator):
    client.get("/api/analytics/hotspots", headers=coordinator)
    client.get("/api/analytics/forecast", headers=coordinator)
    actions = [e["action"] for e in client.get("/api/audit", params={"limit": 50}, headers=coordinator).json()["items"]]
    assert "ANALYTICS_GENERATED" in actions and "FORECAST_GENERATED" in actions
