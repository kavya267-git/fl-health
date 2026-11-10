"""Clusters of potential hotspots: K-Means on the regions flagged this week.

The regions flagged as potential hotspots are grouped by **where** they are and **how high** their rates are:

* location: each region's centroid, projected to kilometres (equirectangular projection around the flagged
  regions' mean latitude; adequate at the scale of a state or district map);
* rates: the case rate per 100,000 (when populations are loaded) and the anomaly score (how far this week is
  above the region's usual level).

Each feature is standardised across the flagged regions, so location (two features) and rate (one or two)
count about equally. K-Means (scikit-learn, 20 starts, fixed seed) is run for k = 2 .. min(5, n - 1) and the k
with the highest silhouette is kept. The grouping is reported only if that silhouette is at least 0.25
(Kaufman & Rousseeuw's threshold for any substantial structure); otherwise, and with fewer than three flagged
regions, there is no cluster layer and the reason is given. Groups of one region are not called clusters.

A cluster says that some flagged regions are near each other and have similar rates. It does not say they
share a cause, and it is not a confirmed event; potential hotspots themselves need confirmation.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional

import numpy as np

EARTH_RADIUS_KM = 6371.0
MIN_REGIONS = 3
MAX_K = 5
MIN_SILHOUETTE = 0.25
LABEL = "Cluster of potential hotspots"


def project_km(lons: np.ndarray, lats: np.ndarray) -> np.ndarray:
    """Equirectangular projection to kilometres around the mean latitude."""
    lat0 = math.radians(float(np.mean(lats)))
    x = EARTH_RADIUS_KM * np.radians(lons) * math.cos(lat0)
    y = EARTH_RADIUS_KM * np.radians(lats)
    return np.column_stack([x, y])


def _standardise(columns: np.ndarray) -> np.ndarray:
    spread = columns.std(axis=0)
    spread[spread == 0] = 1.0
    return (columns - columns.mean(axis=0)) / spread


def _features(regions: List[dict]) -> tuple:
    lons = np.array([r["centroid_lon"] for r in regions], dtype=float)
    lats = np.array([r["centroid_lat"] for r in regions], dtype=float)
    columns = [project_km(lons, lats)]
    used = ["centroid x (km)", "centroid y (km)"]
    rates = [r.get("case_rate") for r in regions]
    if all(v is not None for v in rates):
        columns.append(np.array(rates, dtype=float)[:, None])
        used.append("case rate per 100,000")
    scores = [r.get("anomaly_score") for r in regions]
    if all(v is not None for v in scores):
        columns.append(np.array(scores, dtype=float)[:, None])
        used.append("anomaly score")
    return _standardise(np.hstack(columns)), used


def cluster_flagged(regions: List[dict], seed: int = 0) -> Dict[str, object]:
    """K-Means clusters of the flagged regions.

    ``regions``: flagged regions with ``region_id``, ``region_name``, ``centroid_lon``, ``centroid_lat`` and,
    where known, ``case_rate`` and ``anomaly_score``.
    """
    method = {
        "algorithm": "k-means",
        "k_range": [2, MAX_K],
        "selection": "highest silhouette",
        "min_silhouette": MIN_SILHOUETTE,
        "min_regions": MIN_REGIONS,
        "label": LABEL,
    }
    n = len(regions)
    if n < MIN_REGIONS:
        return {"method": method, "clusters": [], "k": None, "silhouette": None, "features": [],
                "reason": f"{n} potential hotspot{'s' if n != 1 else ''} this week; at least {MIN_REGIONS} are needed to look for clusters."}
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score

    X, used = _features(regions)
    best: Optional[tuple] = None
    for k in range(2, min(MAX_K, n - 1) + 1):
        labels = KMeans(n_clusters=k, n_init=20, random_state=seed).fit_predict(X)
        if len(set(labels)) < 2:
            continue
        score = float(silhouette_score(X, labels))
        if best is None or score > best[0] + 1e-12:
            best = (score, k, labels)
    if best is None or best[0] < MIN_SILHOUETTE:
        score = None if best is None else round(best[0], 3)
        return {"method": method, "clusters": [], "k": None if best is None else best[1], "silhouette": score,
                "features": used,
                "reason": "The potential hotspots do not form clear groups by location and rate"
                + (f" (best silhouette {score:.2f}, below {MIN_SILHOUETTE})." if score is not None else ".")}
    score, k, labels = best
    clusters = []
    for label in sorted(set(labels.tolist())):
        members = [regions[i] for i in range(n) if labels[i] == label]
        if len(members) < 2:
            continue
        clusters.append({"region_ids": [m["region_id"] for m in members], "region_names": [m["region_name"] for m in members]})
    clusters.sort(key=lambda c: c["region_names"][0])
    for number, cluster in enumerate(clusters, start=1):
        cluster["cluster"] = number
        cluster["label"] = f"{LABEL} {number}"
    return {"method": method, "clusters": clusters, "k": k, "silhouette": round(score, 3), "features": used,
            "reason": None if clusters else "Every group holds a single region; no cluster to show."}
