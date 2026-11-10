"""K-Means clusters of potential hotspots: projection, k selection, the silhouette gate, singletons."""

import math

import numpy as np
import pytest

from analytics.hotspot import clusters


def _region(rid, lon, lat, rate=50.0, score=3.0):
    return {"region_id": rid, "region_name": f"Region {rid}", "centroid_lon": lon, "centroid_lat": lat,
            "case_rate": rate, "anomaly_score": score}


def test_projection_is_in_kilometres():
    xy = clusters.project_km(np.array([0.0, 0.0]), np.array([0.0, 1.0]))
    assert xy[1, 1] - xy[0, 1] == pytest.approx(2 * math.pi * 6371 / 360, rel=1e-6)
    near_pole = clusters.project_km(np.array([0.0, 1.0]), np.array([60.0, 60.0]))
    assert near_pole[1, 0] - near_pole[0, 0] == pytest.approx(2 * math.pi * 6371 / 360 * 0.5, rel=1e-6)


def test_too_few_flagged_regions():
    out = clusters.cluster_flagged([_region("A", 0, 0), _region("B", 0.1, 0)])
    assert out["clusters"] == [] and "at least 3" in out["reason"]


def test_two_clear_groups_by_location_and_rate():
    west = [_region(f"W{i}", 0.0 + 0.05 * i, 0.0, rate=20 + i) for i in range(3)]
    east = [_region(f"E{i}", 1.0 + 0.05 * i, 0.0, rate=90 + i) for i in range(3)]
    out = clusters.cluster_flagged(west + east)
    assert out["k"] == 2 and out["silhouette"] >= clusters.MIN_SILHOUETTE
    groups = sorted(sorted(c["region_ids"]) for c in out["clusters"])
    assert groups == [["E0", "E1", "E2"], ["W0", "W1", "W2"]]
    assert all(c["label"].startswith("Cluster of potential hotspots") for c in out["clusters"])
    assert out["features"] == ["centroid x (km)", "centroid y (km)", "case rate per 100,000", "anomaly score"]
    assert clusters.cluster_flagged(west + east) == out  # deterministic


def test_no_clear_structure_gives_no_layer():
    square = [_region("A", 0, 0), _region("B", 1, 0), _region("C", 0, 1), _region("D", 1, 1)]
    out = clusters.cluster_flagged(square)
    assert out["clusters"] == [] and out["silhouette"] < clusters.MIN_SILHOUETTE and "do not form clear groups" in out["reason"]


def test_a_lone_region_is_not_a_cluster():
    pair = [_region("A", 0.0, 0.0, rate=30), _region("B", 0.02, 0.0, rate=31)]
    far = [_region("F", 3.0, 3.0, rate=95)]
    out = clusters.cluster_flagged(pair + far)
    assert [sorted(c["region_ids"]) for c in out["clusters"]] == [["A", "B"]]


def test_rates_are_optional():
    regions = [{**_region(r, x, 0.0), "case_rate": None} for r, x in (("A", 0), ("B", 0.02), ("C", 2.0), ("D", 2.02))]
    out = clusters.cluster_flagged(regions)
    assert "case rate per 100,000" not in out["features"]
    assert sorted(sorted(c["region_ids"]) for c in out["clusters"]) == [["A", "B"], ["C", "D"]]
