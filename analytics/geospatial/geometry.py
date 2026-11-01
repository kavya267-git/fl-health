"""Small GeoJSON geometry helpers (centroid, area, adjacency).

Pure Python so the surveillance layer runs without a GIS stack. When Shapely
is installed it is used for adjacency, which is more robust for real
administrative boundaries whose shared borders do not use identical vertices.
"""

from __future__ import annotations

import importlib.util
from typing import Dict, Iterable, List, Set, Tuple

Ring = List[List[float]]


def _polygons(geometry: dict) -> List[List[Ring]]:
    kind = geometry.get("type")
    if kind == "Polygon":
        return [geometry["coordinates"]]
    if kind == "MultiPolygon":
        return list(geometry["coordinates"])
    raise ValueError(f"Unsupported geometry type '{kind}'. Regions must be Polygon or MultiPolygon.")


def _ring_area_centroid(ring: Ring) -> Tuple[float, float, float]:
    """Signed area and centroid of one ring (shoelace formula)."""
    area = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
        cross = x0 * y1 - x1 * y0
        area += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    area *= 0.5
    if abs(area) < 1e-15:
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        return 0.0, sum(xs) / len(xs), sum(ys) / len(ys)
    return area, cx / (6.0 * area), cy / (6.0 * area)


def area(geometry: dict) -> float:
    """Planar area in squared coordinate units (outer rings minus holes)."""
    total = 0.0
    for polygon in _polygons(geometry):
        for index, ring in enumerate(polygon):
            ring_area = abs(_ring_area_centroid([p[:2] for p in ring])[0])
            total += ring_area if index == 0 else -ring_area
    return total


def centroid(geometry: dict) -> Tuple[float, float]:
    """Area-weighted centroid as (x, y) = (longitude, latitude)."""
    weighted_x = weighted_y = total = 0.0
    for polygon in _polygons(geometry):
        ring_area, cx, cy = _ring_area_centroid([p[:2] for p in polygon[0]])
        weight = abs(ring_area) or 1e-12
        weighted_x += cx * weight
        weighted_y += cy * weight
        total += weight
    return weighted_x / total, weighted_y / total


def _vertex_set(geometry: dict, precision: int) -> Set[Tuple[float, float]]:
    return {
        (round(point[0], precision), round(point[1], precision))
        for polygon in _polygons(geometry)
        for ring in polygon
        for point in ring
    }


def adjacency(features: Iterable[dict], id_property: str = "region_id", precision: int = 6) -> Dict[str, List[str]]:
    """Which regions share a border. Returns ``{region_id: [neighbour ids]}``."""
    features = list(features)
    ids = [feature["properties"][id_property] for feature in features]
    neighbours: Dict[str, Set[str]] = {region_id: set() for region_id in ids}

    if importlib.util.find_spec("shapely") is not None:
        from shapely.geometry import shape  # optional dependency

        shapes = [shape(feature["geometry"]).buffer(0) for feature in features]
        for i in range(len(shapes)):
            for j in range(i + 1, len(shapes)):
                shared = shapes[i].intersection(shapes[j])
                if not shared.is_empty and shared.length > 0:
                    neighbours[ids[i]].add(ids[j])
                    neighbours[ids[j]].add(ids[i])
    else:
        # Regions that share a border segment share at least two vertices.
        vertices = [_vertex_set(feature["geometry"], precision) for feature in features]
        for i in range(len(features)):
            for j in range(i + 1, len(features)):
                if len(vertices[i] & vertices[j]) >= 2:
                    neighbours[ids[i]].add(ids[j])
                    neighbours[ids[j]].add(ids[i])
    return {region_id: sorted(values) for region_id, values in neighbours.items()}


def connected_groups(nodes: Iterable[str], neighbours: Dict[str, List[str]]) -> List[List[str]]:
    """Connected components of ``nodes`` under the adjacency relation."""
    remaining = set(nodes)
    groups = []
    while remaining:
        start = min(remaining)
        stack, group = [start], set()
        while stack:
            node = stack.pop()
            if node in group:
                continue
            group.add(node)
            stack.extend(n for n in neighbours.get(node, []) if n in remaining and n not in group)
        remaining -= group
        groups.append(sorted(group))
    return sorted(groups)
