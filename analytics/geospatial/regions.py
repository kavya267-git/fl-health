"""Surveillance regions: simulated geography and a loader for real boundaries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

import numpy as np

from analytics.geospatial.geometry import adjacency, centroid

#: Fictional place names. Any resemblance to real places is coincidental.
_REGION_NAMES = [
    "Ashgrove",
    "Brackenfield",
    "Calderwick",
    "Dunmere",
    "Eastholm",
    "Fernhollow",
    "Glenmoor",
    "Hartwell",
    "Islebrook",
    "Kestrel Bay",
    "Larchmont",
    "Marlow Heights",
]

#: Abstract coordinate box for the simulated map (degrees). It is not a real place.
_BOUNDS = (0.0, 0.0, 1.6, 1.2)  # min_lon, min_lat, max_lon, max_lat


def _bounded_voronoi(points: np.ndarray, bounds) -> List[List[List[float]]]:
    """Voronoi cells clipped to a rectangle, by mirroring the seeds across each edge."""
    from scipy.spatial import Voronoi

    min_x, min_y, max_x, max_y = bounds
    mirrored = [points]
    for axis, edge in ((0, min_x), (0, max_x), (1, min_y), (1, max_y)):
        reflected = points.copy()
        reflected[:, axis] = 2 * edge - reflected[:, axis]
        mirrored.append(reflected)
    diagram = Voronoi(np.vstack(mirrored))
    cells = []
    for index in range(len(points)):
        region = diagram.regions[diagram.point_region[index]]
        vertices = diagram.vertices[region]
        centre = vertices.mean(axis=0)
        order = np.argsort(np.arctan2(vertices[:, 1] - centre[1], vertices[:, 0] - centre[0]))
        ring = [[round(float(x), 6), round(float(y), 6)] for x, y in vertices[order]]
        ring.append(ring[0])
        cells.append(ring)
    return cells


def simulated_regions(seed: int = 11) -> dict:
    """A GeoJSON FeatureCollection of 12 fictional regions."""
    rng = np.random.default_rng(seed)
    min_x, min_y, max_x, max_y = _BOUNDS
    columns, rows = 4, 3
    seeds = []
    for row in range(rows):
        for column in range(columns):
            x = min_x + (column + 0.5 + rng.uniform(-0.28, 0.28)) * (max_x - min_x) / columns
            y = min_y + (row + 0.5 + rng.uniform(-0.28, 0.28)) * (max_y - min_y) / rows
            seeds.append([x, y])
    cells = _bounded_voronoi(np.array(seeds), _BOUNDS)
    populations = rng.integers(45, 320, size=len(cells)) * 1000

    features = []
    for index, ring in enumerate(cells):
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "region_id": f"R{index + 1:02d}",
                    "name": _REGION_NAMES[index],
                    "population": int(populations[index]),
                },
                "geometry": {"type": "Polygon", "coordinates": [ring]},
            }
        )
    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "simulated_geometry": True,
            "description": "Fictional regions generated as a Voronoi tessellation. Not a real geography.",
        },
    }


def load_regions(
    path: Path,
    id_field: str = "region_id",
    name_field: str = "name",
    population_field: Optional[str] = "population",
) -> dict:
    """Load real region boundaries.

    ``.geojson``/``.json`` files are read directly. Other formats (Shapefile,
    GeoPackage, ...) are read with GeoPandas and reprojected to WGS84, which
    requires the optional ``geopandas`` dependency.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Region boundary file not found: {path}")
    if path.suffix.lower() in (".geojson", ".json"):
        collection = json.loads(path.read_text(encoding="utf-8"))
    else:
        try:
            import geopandas as gpd  # optional dependency
        except ImportError as exc:
            raise RuntimeError(
                f"Reading '{path.suffix}' boundaries needs geopandas. Install it or convert the file to GeoJSON."
            ) from exc
        frame = gpd.read_file(path)
        if frame.crs is not None:
            frame = frame.to_crs(epsg=4326)
        collection = json.loads(frame.to_json())

    if collection.get("type") != "FeatureCollection" or not collection.get("features"):
        raise ValueError("Region file must be a non-empty GeoJSON FeatureCollection")
    features = []
    seen = set()
    for feature in collection["features"]:
        properties = feature.get("properties") or {}
        if id_field not in properties:
            raise ValueError(f"A region feature is missing the id field '{id_field}'")
        region_id = str(properties[id_field])
        if region_id in seen:
            raise ValueError(f"Duplicate region id '{region_id}'")
        seen.add(region_id)
        population = properties.get(population_field) if population_field else None
        if population is not None:
            population = int(population)
            if population <= 0:
                population = None
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "region_id": region_id,
                    "name": str(properties.get(name_field, region_id)),
                    "population": population,
                },
                "geometry": feature["geometry"],
            }
        )
    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "simulated_geometry": False,
            "description": f"Boundaries loaded from {path.name}.",
            # Credit line carried by the file (e.g. the licence and source of public boundaries), shown on the map.
            "attribution": collection.get("attribution"),
            # Caveats about the boundaries themselves (e.g. a district the source does not show separately).
            "notes": collection.get("notes"),
        },
    }


def apply_populations(collection: dict, path: Path) -> int:
    """Set each region's population from a CSV with columns region_id and population. Returns how many matched.

    Regions missing from the file keep no population (their rates are left empty, never guessed).
    """
    import csv

    with open(path, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or not {"region_id", "population"} <= set(rows[0]):
        raise ValueError(f"{Path(path).name} needs the columns region_id and population")
    populations = {row["region_id"].strip(): int(row["population"]) for row in rows if row["population"].strip()}
    matched = 0
    for feature in collection["features"]:
        properties = feature["properties"]
        value = populations.get(properties["region_id"])
        properties["population"] = value if value and value > 0 else None
        matched += properties["population"] is not None
    return matched


def region_table(collection: dict) -> List[dict]:
    """Flat region records (id, name, population, centroid, neighbours)."""
    neighbours = adjacency(collection["features"])
    table = []
    for feature in collection["features"]:
        properties = feature["properties"]
        lon, lat = centroid(feature["geometry"])
        table.append(
            {
                "region_id": properties["region_id"],
                "name": properties["name"],
                "population": properties.get("population"),
                "centroid_lon": lon,
                "centroid_lat": lat,
                "neighbours": neighbours[properties["region_id"]],
                "geometry": feature["geometry"],
            }
        )
    return table
