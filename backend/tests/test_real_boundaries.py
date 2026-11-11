"""Real boundaries through REGIONS_GEOJSON_PATH: Karnataka's districts from geoBoundaries (ODbL 1.0)."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from analytics.geospatial.regions import load_regions
from app.main import create_app
from backend_test_helpers import login

KARNATAKA = Path(__file__).resolve().parents[2] / "data" / "boundaries" / "karnataka_districts.geojson"


def test_the_committed_file_is_karnataka_only_with_its_licence_and_credit():
    collection = json.loads(KARNATAKA.read_text(encoding="utf-8"))
    assert collection["license"] == "ODbL-1.0"
    assert "geoBoundaries" in collection["attribution"] and "ODbL" in collection["attribution"]
    ids = [f["properties"]["region_id"] for f in collection["features"]]
    assert len(ids) == 30 == len(set(ids)) and all(i.startswith("KA-") for i in ids)
    assert {"KA-BANGALORE", "KA-MYSORE", "KA-UDUPI", "KA-BIDAR"} <= set(ids)
    # Only the state: every vertex lies inside a box around Karnataka (about 11.5-18.5 N, 74-78.6 E).
    def vertices(coordinates):
        if isinstance(coordinates[0], (int, float)):
            yield coordinates
        else:
            for c in coordinates:
                yield from vertices(c)

    points = [p for f in collection["features"] for p in vertices(f["geometry"]["coordinates"])]
    assert all(73.9 < lon < 78.7 and 11.4 < lat < 18.6 for lon, lat in points)


def test_loader_reads_ids_names_and_attribution():
    collection = load_regions(KARNATAKA, "region_id", "name", "population")
    assert collection["metadata"]["simulated_geometry"] is False
    assert "ODbL" in collection["metadata"]["attribution"]
    mysore = next(f for f in collection["features"] if f["properties"]["region_id"] == "KA-MYSORE")
    assert mysore["properties"]["name"] == "Mysuru" and mysore["properties"]["population"] is None
    assert "Vijayanagara" in collection["metadata"]["notes"]


def test_current_district_names_with_the_source_spelling_kept():
    features = json.loads(KARNATAKA.read_text(encoding="utf-8"))["features"]
    names = {f["properties"]["source_name"]: f["properties"]["name"] for f in features}
    assert names["Bangalore"] == "Bengaluru Urban" and names["Bangalore Rural"] == "Bengaluru Rural"
    assert names["Belgaum"] == "Belagavi" and names["Gulbarga"] == "Kalaburagi" and names["Shimoga"] == "Shivamogga"
    assert names["Kodagu"] == "Kodagu"  # unchanged names stay as they are
    assert {f["properties"]["region_id"] for f in features} >= {"KA-BANGALORE", "KA-MYSORE"}  # ids do not change


@pytest.fixture()
def karnataka_client(settings):
    settings = settings.model_copy(update={"regions_geojson_path": KARNATAKA})
    with TestClient(create_app(settings)) as client:
        yield client


def test_api_serves_karnataka_districts_with_simulated_reports_labelled(karnataka_client):
    viewer = login(karnataka_client, "viewer@fl-healthcare.demo")
    options = karnataka_client.get("/api/analytics/options", headers=viewer).json()
    assert len(options["regions"]) == 30
    assert options["data_status"]["simulated"] is True  # the weekly reports are still simulated
    assert options["data_status"]["geometry_simulated"] is False
    assert "geoBoundaries" in options["data_status"]["geometry_attribution"]
    assert "Vijayanagara" in options["data_status"]["geometry_notes"]
    assert options["data_status"]["watermark"] == "SIMULATED DATA \u2013 NOT REAL CASES"
    assert {r["name"] for r in options["regions"]} >= {"Bengaluru Urban", "Mysuru"}

    hotspots = karnataka_client.get("/api/analytics/hotspots", params={"disease": "dengue"}, headers=viewer).json()
    assert len(hotspots["geojson"]["features"]) == 30
    assert sum(hotspots["summary"].values()) == 30


def test_admin_gives_a_health_officer_karnataka_districts(karnataka_client):
    admin = login(karnataka_client, "admin@fl-healthcare.demo")
    created = karnataka_client.post("/api/auth/register", json={"email": "dho@example.org", "password": "long-enough-pw"})
    user_id = created.json()["user"]["id"]
    response = karnataka_client.post(
        f"/api/users/{user_id}/role", headers=admin, json={"role": "health_officer", "jurisdiction": ["KA-MYSORE", "KA-MANDYA"]}
    )
    assert response.status_code == 200
    token = karnataka_client.post("/api/auth/demo-login", json={"email": "dho@example.org", "password": "long-enough-pw"})
    officer = {"Authorization": f"Bearer {token.json()['access_token']}"}
    regions = karnataka_client.get("/api/analytics/options", headers=officer).json()["regions"]
    assert [r["region_id"] for r in regions] == ["KA-MANDYA", "KA-MYSORE"]
    outside = karnataka_client.get("/api/analytics/forecast", params={"region_id": "KA-UDUPI", "horizon": 2}, headers=officer)
    assert outside.status_code == 403


HOMES = {"hospital_a": "KA-DHARWAD", "hospital_b": "KA-BELGAUM", "hospital_c": "KA-BANGALORE", "hospital_d": "KA-MYSORE"}
NORTH = ["KA-BELGAUM", "KA-BAGALKOT", "KA-BIJAPUR", "KA-DHARWAD", "KA-GADAG", "KA-HAVERI", "KA-UTTARA-KANNADA"]
SOUTH = ["KA-MYSORE", "KA-CHAMARAJANAGAR", "KA-MANDYA", "KA-HASSAN", "KA-KODAGU", "KA-CHIKMAGALUR",
         "KA-DAKSHINA-KANNADA", "KA-UDUPI"]


def test_home_regions_place_each_simulated_hospital_in_its_district():
    from analytics.geospatial.regions import region_table
    from analytics.geospatial.surveillance import assign_catchments

    table = region_table(load_regions(KARNATAKA, "region_id", "name", "population"))
    shares = assign_catchments(table, list(HOMES), HOMES)
    for hospital_id, region_id in HOMES.items():
        assert shares[region_id][hospital_id] == 0.7  # a home district is mostly its own hospital's
    assert all(sorted(s.values()) == [0.3, 0.7] for s in shares.values())
    with pytest.raises(ValueError, match="KA-NOWHERE"):
        assign_catchments(table, list(HOMES), {"hospital_a": "KA-NOWHERE"})


@pytest.fixture()
def karnataka_demo_client(settings):
    settings = settings.model_copy(update={
        "regions_geojson_path": KARNATAKA,
        "demo_hospital_regions": HOMES,
        "demo_officer_jurisdictions": {
            "north": {"label": "Belagavi division", "regions": NORTH},
            "south": {"label": "Mysuru division", "regions": SOUTH},
        },
    })
    with TestClient(create_app(settings)) as client:
        yield client


def test_demo_officers_and_hospitals_use_the_configured_districts(karnataka_demo_client):
    client = karnataka_demo_client
    accounts = {a["email"]: a for a in client.get("/api/system/config").json()["demo_accounts"]}
    assert accounts["officer_north@fl-healthcare.demo"]["jurisdiction"] == NORTH
    assert accounts["officer_north@fl-healthcare.demo"]["display_name"] == "Health officer, Belagavi division"
    assert accounts["officer_south@fl-healthcare.demo"]["jurisdiction"] == SOUTH

    north = login(client, "officer_north@fl-healthcare.demo")
    regions = client.get("/api/analytics/options", headers=north).json()["regions"]
    assert sorted(r["region_id"] for r in regions) == sorted(NORTH)

    names = [r["name"] for r in client.get("/api/registrations/regions").json()]
    assert len(names) == 30 and names == sorted(names) and "Bengaluru Urban" in names

    manager = login(client, "manager_a@fl-healthcare.demo")
    me = client.get("/api/auth/me", headers=manager).json()
    assert me["hospital_id"] == "hospital_a"


def test_without_the_settings_the_officers_keep_the_simulated_regions(karnataka_client):
    accounts = {a["email"]: a for a in karnataka_client.get("/api/system/config").json()["demo_accounts"]}
    assert accounts["officer_north@fl-healthcare.demo"]["jurisdiction"] == ["R01", "R02", "R03", "R04", "R05", "R06"]
