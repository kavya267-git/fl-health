"""The K-Means layer in the hotspot API, and how it is scoped for health officers."""

from app.analytics.surveillance_service import scope_hotspots
from backend_test_helpers import login


def test_hotspot_response_carries_the_cluster_layer(client, viewer):
    body = client.get("/api/analytics/hotspots", params={"disease": "dengue"}, headers=viewer).json()
    layer = body["hotspot_clusters"]
    assert layer["method"]["algorithm"] == "k-means" and layer["method"]["label"] == "Cluster of potential hotspots"
    flagged = {r["region_id"] for r in body["regions"] if r["hotspot_flag"]}
    members = {rid: c["cluster"] for c in layer["clusters"] for rid in c["region_ids"]}
    assert set(members) <= flagged  # only potential hotspots are clustered
    assert all(len(c["region_ids"]) >= 2 for c in layer["clusters"])
    assert {f["properties"]["region_id"]: f["properties"]["potential_hotspot_cluster"] for f in body["geojson"]["features"]} == {
        r["region_id"]: members.get(r["region_id"]) for r in body["regions"]
    }
    assert layer["clusters"] or layer["reason"]


def _payload():
    regions = [{"region_id": r, "status": "CANDIDATE_HOTSPOT", "adjacent_flagged_regions": [], "potential_hotspot_cluster": c}
               for r, c in (("R01", 1), ("R02", 1), ("R07", 1), ("R08", 2), ("R09", 2))]
    return {
        "regions": regions,
        "geojson": {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"region_id": r["region_id"], "potential_hotspot_cluster": r["potential_hotspot_cluster"]}}
            for r in regions
        ]},
        "summary": {"CANDIDATE_HOTSPOT": 5},
        "hotspot_clusters": {"method": {}, "clusters": [
            {"cluster": 1, "label": "Cluster of potential hotspots 1", "region_ids": ["R01", "R02", "R07"], "region_names": ["a", "b", "g"]},
            {"cluster": 2, "label": "Cluster of potential hotspots 2", "region_ids": ["R08", "R09"], "region_names": ["h", "i"]},
        ]},
    }


def test_officer_sees_a_cluster_only_with_two_of_its_regions():
    north = scope_hotspots(_payload(), ["R01", "R02", "R03", "R08"])
    assert [c["region_ids"] for c in north["hotspot_clusters"]["clusters"]] == [["R01", "R02"]]
    assert {r["region_id"]: r["potential_hotspot_cluster"] for r in north["regions"]} == {"R01": 1, "R02": 1, "R08": None}
    assert {f["properties"]["region_id"]: f["properties"]["potential_hotspot_cluster"] for f in north["geojson"]["features"]} == {
        "R01": 1, "R02": 1, "R08": None
    }
    # Nothing outside the jurisdiction leaks through the layer.
    assert all(rid in {"R01", "R02", "R03", "R08"} for c in north["hotspot_clusters"]["clusters"] for rid in c["region_ids"])


def test_officer_response_has_no_foreign_cluster_members(client):
    north = login(client, "officer_north@fl-healthcare.demo")
    body = client.get("/api/analytics/hotspots", params={"disease": "dengue"}, headers=north).json()
    allowed = {r["region_id"] for r in body["regions"]}
    assert all(set(c["region_ids"]) <= allowed for c in body["hotspot_clusters"]["clusters"])
