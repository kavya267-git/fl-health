"""Screening of incoming model updates for unusual ones (Isolation Forest). A flag for people, never a rejection.

For every valid update of a round, at aggregation, the coordinator measures:

* **relative norm**: the update's size ‖W_hospital − W_global‖₂ divided by the median size of this round's
  updates. Raw sizes shrink as training converges, so they are compared within the round;
* **cosine distance to the mean update**: 1 − cos(Δ_hospital, mean of the *other* hospitals' updates, each scaled
  to unit length). 0 means the hospital moved the model the same way as the others on average; 1 means at right
  angles; up to 2 means opposite. Leaving the hospital out and scaling to unit length keep one very large update
  from dragging the mean towards itself, which would make every other hospital look unusual instead.

An Isolation Forest (Liu et al., 2008) is fitted on these two features, log relative norm and cosine distance,
of the most recent earlier updates of the same model (up to ``HISTORY_WINDOW``) plus this round's, and each of this round's updates gets an anomaly
score. An update is flagged as unusual when the forest isolates it faster than expected (scikit-learn's
"auto" threshold, score above 0.5). With fewer than ``MIN_HISTORY`` earlier updates there is too little to compare
against, and nothing is scored.

A flag is information, not a verdict: a hospital whose patients differ from the others' (non-IID data), a small
hospital, or differential-privacy noise can all produce unusual updates. Flagged updates are aggregated like any
other; the flag appears on the round page and in the audit log.
"""

from __future__ import annotations

import math
from typing import Dict, Iterable, List, Optional

import numpy as np

from analytics.privacy.dp import is_statistic

#: Earlier updates of the same model needed before anything is scored (five rounds of four hospitals).
MIN_HISTORY = 20
#: Only the most recent earlier updates are compared with: update directions drift as training converges.
HISTORY_WINDOW = 100
#: scikit-learn's "auto" threshold on the anomaly score (score_samples is its negative).
SCORE_THRESHOLD = 0.5
N_ESTIMATORS = 200

Weights = Dict[str, np.ndarray]


def _delta(base: Weights, weights: Weights) -> np.ndarray:
    keys = [
        k
        for k in sorted(base)
        if np.issubdtype(np.asarray(base[k]).dtype, np.floating) and not is_statistic(k)
    ]
    return np.concatenate(
        [(np.asarray(weights[k], dtype=np.float64) - np.asarray(base[k], dtype=np.float64)).ravel() for k in keys]
    )


def update_features(base: Weights, updates: Dict[str, Weights]) -> Dict[str, dict]:
    """Norm, relative norm and cosine distance to the others' mean update, per hospital. Batch-norm statistics excluded."""
    deltas = {h: _delta(base, w) for h, w in updates.items()}
    if not deltas:
        return {}
    norms = {h: float(np.linalg.norm(d)) for h, d in deltas.items()}
    median = float(np.median(list(norms.values())))
    units = {h: d / norms[h] if norms[h] > 0 else d for h, d in deltas.items()}
    out = {}
    for h, d in deltas.items():
        others = [units[o] for o in units if o != h]
        mean = np.mean(np.stack(others), axis=0) if others else units[h]
        mean_norm = float(np.linalg.norm(mean))
        cosine = float(d @ mean / (norms[h] * mean_norm)) if norms[h] > 0 and mean_norm > 0 else 1.0
        out[h] = {
            "norm": norms[h],
            "relative_norm": norms[h] / median if median > 0 else 1.0,
            "cosine_distance": float(min(2.0, max(0.0, 1.0 - cosine))),
        }
    return out


def _matrix(rows: Iterable[dict]) -> np.ndarray:
    return np.array([[math.log(max(r["relative_norm"], 1e-12)), r["cosine_distance"]] for r in rows], dtype=np.float64)


def screen(current: Dict[str, dict], history: List[dict], seed: int = 0) -> Dict[str, dict]:
    """Score this round's updates against the earlier ones. ``history``: feature dicts of earlier updates."""
    history = history[-HISTORY_WINDOW:]
    base = {"method": "isolation_forest", "history_size": len(history), "flag_is_advisory": True}
    if len(history) < MIN_HISTORY:
        return {
            h: {**f, **base, "scored": False, "score": None, "flagged": False,
                "reason": f"Not scored: {len(history)} earlier update(s), {MIN_HISTORY} needed."}
            for h, f in current.items()
        }
    from sklearn.ensemble import IsolationForest

    hospitals = list(current)
    reference = _matrix(history + [current[h] for h in hospitals])
    forest = IsolationForest(n_estimators=N_ESTIMATORS, contamination="auto", random_state=seed).fit(reference)
    scores = -forest.score_samples(_matrix(current[h] for h in hospitals))
    out = {}
    for h, score in zip(hospitals, scores):
        flagged = bool(score > SCORE_THRESHOLD)
        out[h] = {**current[h], **base, "scored": True, "score": float(score), "flagged": flagged,
                  "reason": _reason(current[h]) if flagged else None}
    return out


def _reason(features: dict) -> str:
    parts = []
    if features["relative_norm"] >= 2 or features["relative_norm"] <= 0.5:
        parts.append(f"its size is {features['relative_norm']:.1f}× this round's median")
    if features["cosine_distance"] >= 0.5:
        parts.append(f"its direction differs from the other hospitals' average (cosine distance {features['cosine_distance']:.2f})")
    detail = " and ".join(parts) if parts else "its combination of size and direction is rare among earlier updates"
    return f"Unusual compared with earlier updates: {detail}. Still used in the average."


def history_rows(rows: Iterable[Optional[dict]]) -> List[dict]:
    """Feature dicts from stored screening records (skipping updates that were never screened)."""
    return [
        {"relative_norm": float(r["relative_norm"]), "cosine_distance": float(r["cosine_distance"])}
        for r in rows
        if r and r.get("relative_norm") is not None and r.get("cosine_distance") is not None
    ]
