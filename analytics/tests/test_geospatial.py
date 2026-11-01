"""Regions, geometry, aggregated reports and their validation."""

import json
from datetime import date

import pandas as pd
import pytest

from analytics.geospatial.geometry import adjacency, area, centroid, connected_groups
from analytics.geospatial.regions import load_regions, region_table, simulated_regions
from analytics.geospatial.surveillance import (
    ReportValidationError,
    aggregate_regional,
    case_rate_per_100k,
    iso_week_label,
    last_complete_week,
    simulate_reports,
    validate_reports,
    week_start,
)

HOSPITALS = ["hospital_a", "hospital_b", "hospital_c", "hospital_d"]
SQUARE = {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]}


def _feature(region_id, x0):
    ring = [[x0, 0], [x0 + 1, 0], [x0 + 1, 1], [x0, 1], [x0, 0]]
    return {
        "type": "Feature",
        "properties": {"region_id": region_id, "name": region_id, "population": 1000},
        "geometry": {"type": "Polygon", "coordinates": [ring]},
    }


def test_area_and_centroid():
    assert area(SQUARE) == pytest.approx(4.0)
    assert centroid(SQUARE) == pytest.approx((1.0, 1.0))
    with_hole = {
        "type": "Polygon",
        "coordinates": [SQUARE["coordinates"][0], [[0.5, 0.5], [1.5, 0.5], [1.5, 1.5], [0.5, 1.5], [0.5, 0.5]]],
    }
    assert area(with_hole) == pytest.approx(3.0)
    multi = {
        "type": "MultiPolygon",
        "coordinates": [SQUARE["coordinates"], [[[10, 0], [12, 0], [12, 2], [10, 2], [10, 0]]]],
    }
    assert area(multi) == pytest.approx(8.0) and centroid(multi)[0] == pytest.approx(6.0)
    with pytest.raises(ValueError):
        area({"type": "Point", "coordinates": [0, 0]})


def test_adjacency_and_groups():
    features = [_feature("A", 0), _feature("B", 1), _feature("C", 5)]
    neighbours = adjacency(features)
    assert neighbours == {"A": ["B"], "B": ["A"], "C": []}
    assert connected_groups(["A", "B", "C"], neighbours) == [["A", "B"], ["C"]]


def test_simulated_regions_tile_the_map_without_overlap():
    collection = simulated_regions()
    assert collection["metadata"]["simulated_geometry"] is True
    table = region_table(collection)
    assert len(table) == 12 and len({r["region_id"] for r in table}) == 12
    assert sum(area(r["geometry"]) for r in table) == pytest.approx(1.6 * 1.2, rel=1e-6)
    for region in table:
        assert region["population"] > 0 and region["neighbours"]
        for other in region["neighbours"]:  # adjacency is symmetric
            assert region["region_id"] in next(r for r in table if r["region_id"] == other)["neighbours"]
        ring = region["geometry"]["coordinates"][0]
        assert ring[0] == ring[-1]
    assert json.dumps(collection)  # valid GeoJSON-serialisable structure


def test_real_boundaries_can_be_loaded_from_geojson(tmp_path):
    path = tmp_path / "districts.geojson"
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"code": "D1", "district": "North", "pop": 5000},
                        "geometry": SQUARE,
                    },
                    {
                        "type": "Feature",
                        "properties": {"code": "D2", "district": "South", "pop": 0},
                        "geometry": SQUARE,
                    },
                ],
            }
        )
    )
    collection = load_regions(path, "code", "district", "pop")
    assert collection["metadata"]["simulated_geometry"] is False
    first, second = collection["features"]
    assert first["properties"] == {"region_id": "D1", "name": "North", "population": 5000}
    assert second["properties"]["population"] is None  # zero is not a valid denominator
    with pytest.raises(ValueError, match="id field"):
        load_regions(path, "missing_field")
    with pytest.raises(FileNotFoundError):
        load_regions(tmp_path / "nope.geojson")


def test_week_helpers():
    assert week_start(date(2025, 1, 1)) == date(2024, 12, 30)
    assert last_complete_week(date(2025, 1, 1)) == date(2024, 12, 23)
    assert iso_week_label(date(2024, 12, 30)) == "2025-W01"


@pytest.fixture(scope="module")
def reports():
    table = region_table(simulated_regions())
    return table, simulate_reports(table, HOSPITALS, date(2025, 3, 3), weeks=60, seed=1)


def test_simulated_reports_are_aggregates_with_small_cells_suppressed(reports):
    table, frame = reports
    assert list(frame.columns) == ["hospital_id", "region_id", "disease", "week_start", "case_count", "suppressed"]
    assert frame["week_start"].nunique() == 60 and frame["week_start"].max() == "2025-03-03"
    present = frame["case_count"].dropna()
    assert ((present == 0) | (present >= 5)).all()
    assert frame.loc[frame["suppressed"], "case_count"].isna().all()
    assert frame["suppressed"].any()
    validate_reports(frame, [r["region_id"] for r in table], HOSPITALS)


def test_regional_total_is_withheld_when_a_cell_is_suppressed():
    frame = pd.DataFrame(
        [
            ("hospital_a", "R01", "dengue", "2025-03-03", 12, False),
            ("hospital_b", "R01", "dengue", "2025-03-03", None, True),
            ("hospital_a", "R02", "dengue", "2025-03-03", 12, False),
            ("hospital_b", "R02", "dengue", "2025-03-03", 8, False),
        ],
        columns=["hospital_id", "region_id", "disease", "week_start", "case_count", "suppressed"],
    )
    regional = aggregate_regional(frame).set_index("region_id")
    assert pd.isna(regional.loc["R01", "case_count"]) and not regional.loc["R01", "complete"]
    assert regional.loc["R01", "suppressed_cells"] == 1
    assert regional.loc["R02", "case_count"] == 20 and regional.loc["R02", "complete"]
    assert regional.loc["R02", "reporting_hospitals"] == 2


def test_case_rate_needs_a_valid_population():
    assert case_rate_per_100k(50, 200_000) == pytest.approx(25.0)
    assert case_rate_per_100k(50, None) is None
    assert case_rate_per_100k(50, 0) is None
    assert case_rate_per_100k(None, 1000) is None


def test_report_validation_lists_every_problem():
    frame = pd.DataFrame(
        [
            ("hospital_a", "R01", "dengue", "2025-03-04", 3, False),  # Tuesday; count below threshold
            ("hospital_z", "R99", "dengue", "2025-03-03", -1, False),  # unknown ids; negative
            ("hospital_a", "R01", "dengue", "2025-03-04", 3, False),  # duplicate
        ],
        columns=["hospital_id", "region_id", "disease", "week_start", "case_count", "suppressed"],
    )
    with pytest.raises(ReportValidationError) as error:
        validate_reports(frame, ["R01"], HOSPITALS)
    text = " | ".join(error.value.problems)
    for fragment in (
        "Unknown region",
        "Unknown hospital",
        "Monday",
        "negative",
        "suppressed before reporting",
        "Duplicate",
    ):
        assert fragment in text
    with pytest.raises(ReportValidationError, match="Missing columns"):
        validate_reports(frame.drop(columns=["disease"]), ["R01"], HOSPITALS)
