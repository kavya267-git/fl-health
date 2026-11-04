"""Build data/boundaries/karnataka_districts.geojson from geoBoundaries (run once; the output is committed).

    python scripts/extract_karnataka_districts.py ADM1_simplified.geojson ADM2_simplified.geojson

Inputs, release 9469f09 of github.com/wmgeolab/geoBoundaries (gbOpen, India):
  * geoBoundaries-IND-ADM2_simplified.geojson: districts. Licence ODbL 1.0; source Pathways Data Pvt. Ltd.,
    lgdirectory.gov.in (boundary year 2021). This is the data the output contains.
  * geoBoundaries-IND-ADM1_simplified.geojson: states, used only to choose which districts lie in Karnataka
    (a district is kept when its centroid falls inside the Karnataka outline). Nothing from it is written out.

The output holds only Karnataka's districts, so the map shows the state and no national boundary. Region ids
are short and stable ("KA-" plus the district name); the geoBoundaries shapeID is kept as source_shape_id.
Coordinates are rounded to 5 decimals (about 1 m). District names are shown in their current official
form (CURRENT_NAMES, mostly the 2014 renamings); the source spelling is kept as source_name. Region ids are
built from the source spelling and do not change.
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analytics.geospatial.geometry import centroid  # noqa: E402

OUTPUT = ROOT / "data" / "boundaries" / "karnataka_districts.geojson"
STATE = "Karnataka"
#: Source spelling -> current official name, for display.
CURRENT_NAMES = {
    "Bangalore": "Bengaluru Urban",
    "Bangalore Rural": "Bengaluru Rural",
    "Belgaum": "Belagavi",
    "Bellary": "Ballari",
    "Bijapur": "Vijayapura",
    "Chikmagalur": "Chikkamagaluru",
    "Gulbarga": "Kalaburagi",
    "Mysore": "Mysuru",
    "Shimoga": "Shivamogga",
    "Tumkur": "Tumakuru",
}
NOTES = (
    "District boundaries as of 2021 (30 districts). Vijayanagara, formed from Ballari in 2021, is not separate "
    "in this source and is included in Ballari."
)
ATTRIBUTION = (
    "District boundaries: geoBoundaries (Runfola et al. 2020, www.geoboundaries.org), gbOpen IND ADM2, "
    "source Pathways Data Pvt. Ltd. / lgdirectory.gov.in, licensed under the Open Database License (ODbL) 1.0. "
    "Karnataka subset, coordinates rounded, made by scripts/extract_karnataka_districts.py."
)


def plain(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def point_in_ring(x: float, y: float, ring) -> bool:
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def point_in_geometry(x: float, y: float, geometry: dict) -> bool:
    polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    for rings in polygons:
        if point_in_ring(x, y, rings[0]) and not any(point_in_ring(x, y, hole) for hole in rings[1:]):
            return True
    return False


def rounded(coordinates):
    if isinstance(coordinates[0], (int, float)):
        return [round(coordinates[0], 5), round(coordinates[1], 5)]
    return [rounded(c) for c in coordinates]


def main(adm1_path: str, adm2_path: str) -> None:
    states = json.loads(Path(adm1_path).read_text(encoding="utf-8"))["features"]
    state = next(f for f in states if plain(f["properties"]["shapeName"]).lower() == STATE.lower())
    districts = json.loads(Path(adm2_path).read_text(encoding="utf-8"))["features"]
    features = []
    for feature in districts:
        lon, lat = centroid(feature["geometry"])
        if not point_in_geometry(lon, lat, state["geometry"]):
            continue
        name = feature["properties"]["shapeName"]
        slug = re.sub(r"[^A-Z0-9]+", "-", plain(name).upper()).strip("-")
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "region_id": f"KA-{slug}",
                    "name": CURRENT_NAMES.get(name, name),
                    "source_name": name,
                    "source_shape_id": feature["properties"]["shapeID"],
                },
                "geometry": {"type": feature["geometry"]["type"], "coordinates": rounded(feature["geometry"]["coordinates"])},
            }
        )
    features.sort(key=lambda f: f["properties"]["region_id"])
    collection = {
        "type": "FeatureCollection",
        "name": "karnataka_districts",
        "attribution": ATTRIBUTION,
        "license": "ODbL-1.0",
        "notes": NOTES,
        "features": features,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(collection, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"{len(features)} districts written to {OUTPUT}")
    for f in features:
        print(" ", f["properties"]["region_id"], ascii(f["properties"]["source_name"]), "->", ascii(f["properties"]["name"]))


if __name__ == "__main__":
    main(*sys.argv[1:3])
