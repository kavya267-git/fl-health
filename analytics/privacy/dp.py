"""Differential-privacy mechanism for model updates (PROTOTYPE).

What is implemented, for real, at the hospital node before an update leaves:

1. the update ``delta = W_local - W_global`` is clipped to an L2 norm of at
   most ``clip_norm``;
2. Gaussian noise with standard deviation ``noise_multiplier * clip_norm`` is
   added to every clipped coordinate.

What is *not* claimed: this is a prototype. The accounting below is a simple
zero-concentrated-DP bound under stated assumptions, it has not been audited,
and batch-normalisation running statistics are sent unmodified (they are
excluded from clipping and noise because noising a running variance can make
it negative). Treat the reported epsilon as indicative, not as a guarantee.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Dict, Iterable, List, Tuple

import numpy as np

Weights = Dict[str, np.ndarray]

#: Tensors that are statistics rather than trained parameters.
_STATISTIC_SUFFIXES = ("running_mean", "running_var", "num_batches_tracked")

ACCOUNTING_ASSUMPTIONS = [
    "The protected unit is one hospital's whole model update in a round (not an individual patient).",
    "Sensitivity equals clip_norm: neighbouring inputs differ by one hospital's update being present or absent.",
    "Each round is a Gaussian mechanism with rho = 1 / (2 * noise_multiplier^2) under zero-concentrated DP; rounds compose additively.",
    "Epsilon is derived with epsilon = rho + 2 * sqrt(rho * ln(1 / delta)).",
    "No amplification by subsampling is assumed.",
    "Batch-normalisation running statistics are transmitted without clipping or noise and fall outside this bound.",
    "A round run without DP has no formal bound, so the cumulative figure only holds if every round used DP.",
]


@dataclass
class DPConfig:
    enabled: bool = False
    clip_norm: float = 1.0
    noise_multiplier: float = 0.0
    delta: float = 1e-5

    def validate(self) -> None:
        if not self.enabled:
            return
        if not (self.clip_norm > 0):
            raise ValueError("clip_norm must be positive when differential privacy is enabled")
        if not (self.noise_multiplier > 0):
            raise ValueError("noise_multiplier must be positive when differential privacy is enabled")
        if not (0 < self.delta < 1):
            raise ValueError("delta must be in (0, 1)")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict | None) -> "DPConfig":
        payload = payload or {}
        return cls(
            enabled=bool(payload.get("enabled", False)),
            clip_norm=float(payload.get("clip_norm", 1.0)),
            noise_multiplier=float(payload.get("noise_multiplier", 0.0)),
            delta=float(payload.get("delta", 1e-5)),
        )


def is_statistic(key: str) -> bool:
    return key.endswith(_STATISTIC_SUFFIXES)


def _trainable_keys(weights: Weights) -> List[str]:
    return [
        key
        for key in sorted(weights)
        if np.issubdtype(np.asarray(weights[key]).dtype, np.floating) and not is_statistic(key)
    ]


def update_norm(global_weights: Weights, local_weights: Weights) -> float:
    total = 0.0
    for key in _trainable_keys(global_weights):
        diff = np.asarray(local_weights[key], dtype=np.float64) - np.asarray(global_weights[key], dtype=np.float64)
        total += float(np.sum(diff * diff))
    return math.sqrt(total)


def privatize_update(
    global_weights: Weights,
    local_weights: Weights,
    config: DPConfig,
    rng: np.random.Generator,
) -> Tuple[Weights, dict]:
    """Clip and noise the update. Returns the weights to transmit and a report."""
    norm_before = update_norm(global_weights, local_weights)
    report = {
        "enabled": bool(config.enabled),
        "prototype": True,
        "mechanism": "none",
        "update_norm_before": norm_before,
        "clip_norm": None,
        "clipped": False,
        "noise_multiplier": None,
        "noise_std": None,
        "delta": None,
        "noised_tensors": 0,
        "unprotected_tensors": [],
    }
    if not config.enabled:
        return {key: np.asarray(value).copy() for key, value in local_weights.items()}, report

    config.validate()
    scale = min(1.0, config.clip_norm / norm_before) if norm_before > 0 else 1.0
    noise_std = config.noise_multiplier * config.clip_norm
    trainable = set(_trainable_keys(global_weights))
    private: Weights = {}
    for key, local in local_weights.items():
        local = np.asarray(local)
        if key not in trainable:
            private[key] = local.copy()
            continue
        base = np.asarray(global_weights[key], dtype=np.float64)
        delta = (local.astype(np.float64) - base) * scale
        delta += rng.normal(0.0, noise_std, size=delta.shape)
        private[key] = (base + delta).astype(local.dtype)

    report.update(
        {
            "mechanism": "gaussian",
            "clip_norm": float(config.clip_norm),
            "clipped": bool(scale < 1.0),
            "noise_multiplier": float(config.noise_multiplier),
            "noise_std": float(noise_std),
            "delta": float(config.delta),
            "noised_tensors": len(trainable),
            "unprotected_tensors": sorted(k for k in local_weights if k not in trainable),
        }
    )
    return private, report


def gaussian_rho(noise_multiplier: float) -> float:
    """zCDP parameter of one Gaussian release with sensitivity equal to the clip norm."""
    if noise_multiplier <= 0:
        return math.inf
    return 1.0 / (2.0 * noise_multiplier**2)


def zcdp_to_epsilon(rho: float, delta: float) -> float:
    if math.isinf(rho):
        return math.inf
    if rho <= 0:
        return 0.0
    return rho + 2.0 * math.sqrt(rho * math.log(1.0 / delta))


def account_rounds(dp_reports: Iterable[dict], delta: float = 1e-5) -> dict:
    """Cumulative privacy accounting for one hospital and one model.

    ``dp_reports`` holds the DP report of each update the hospital has sent.
    """
    reports = list(dp_reports)
    dp_rounds = [r for r in reports if r and r.get("enabled") and (r.get("noise_multiplier") or 0) > 0]
    non_dp_rounds = len(reports) - len(dp_rounds)
    rho_total = sum(gaussian_rho(float(r["noise_multiplier"])) for r in dp_rounds)
    epsilon_dp_rounds = zcdp_to_epsilon(rho_total, delta) if dp_rounds else None
    formal = bool(dp_rounds) and non_dp_rounds == 0
    return {
        "prototype": True,
        "rounds_total": len(reports),
        "rounds_with_dp": len(dp_rounds),
        "rounds_without_dp": non_dp_rounds,
        "rho": rho_total if dp_rounds else None,
        "delta": delta,
        "epsilon_over_dp_rounds": epsilon_dp_rounds,
        "bound_covers_all_rounds": formal,
        "assumptions": list(ACCOUNTING_ASSUMPTIONS),
    }
