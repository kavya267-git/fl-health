"""Occlusion sensitivity for signals and images.

Hide one part of the input, re-run the model, and record how far the model's
confidence in the explained class falls. Parts whose removal lowers it most
are the parts the model relied on. Confidence is measured in log-odds so that
a prediction at 99.9% still shows which parts support it. The method is
model-agnostic, so it works for any backend.
"""

from __future__ import annotations

from typing import Callable

import numpy as np

PredictFn = Callable[[np.ndarray], np.ndarray]


def _log_odds(probability: np.ndarray) -> np.ndarray:
    """Confidence on the log-odds scale, which does not flatten out near 0% or 100%."""
    clipped = np.clip(np.asarray(probability, dtype=np.float64), 1e-9, 1 - 1e-9)
    return np.log(clipped / (1 - clipped))


SIGNAL_METHOD = "Occlusion sensitivity (sliding window replaced by a straight line; change in log-odds)"
IMAGE_METHOD = "Occlusion sensitivity (sliding patch replaced by the image mean; change in log-odds)"


def occlusion_signal(
    predict: PredictFn, signal: np.ndarray, target_class: int, window: int = 12, stride: int = 4
) -> dict:
    """Per-sample importance for a 1-D signal of shape [length]."""
    signal = np.asarray(signal, dtype=np.float32).reshape(-1)
    length = len(signal)
    if window < 2 or window > length:
        raise ValueError("window must be between 2 and the signal length")
    starts = list(range(0, length - window + 1, stride))
    if starts[-1] != length - window:
        starts.append(length - window)

    batch = np.repeat(signal[None, :], len(starts) + 1, axis=0)
    for row, start in enumerate(starts, start=1):
        end = start + window
        left = signal[start]
        right = signal[end - 1]
        batch[row, start:end] = np.linspace(left, right, window)
    probabilities = np.asarray(predict(batch), dtype=np.float64)[:, target_class]
    reference = probabilities[0]
    confidence = _log_odds(probabilities)

    importance = np.zeros(length, dtype=np.float64)
    coverage = np.zeros(length, dtype=np.float64)
    for row, start in enumerate(starts, start=1):
        importance[start : start + window] += confidence[0] - confidence[row]
        coverage[start : start + window] += 1.0
    importance /= np.maximum(coverage, 1.0)
    return {
        "importance": importance,
        "reference_probability": float(reference),
        "window": window,
        "stride": stride,
        "evaluations": len(starts) + 1,
    }


def occlusion_image(predict: PredictFn, image: np.ndarray, target_class: int, patch: int = 12, stride: int = 4) -> dict:
    """Per-pixel importance for one image of shape [H, W]."""
    image = np.asarray(image)
    height, width = image.shape
    if patch < 2 or patch > min(height, width):
        raise ValueError("patch must be between 2 and the image size")
    fill = image.mean()
    rows = list(range(0, height - patch + 1, stride))
    cols = list(range(0, width - patch + 1, stride))
    positions = [(r, c) for r in rows for c in cols]

    batch = np.repeat(image[None], len(positions) + 1, axis=0)
    for index, (r, c) in enumerate(positions, start=1):
        batch[index, r : r + patch, c : c + patch] = fill
    probabilities = np.asarray(predict(batch), dtype=np.float64)[:, target_class]
    reference = probabilities[0]
    confidence = _log_odds(probabilities)

    importance = np.zeros((height, width), dtype=np.float64)
    coverage = np.zeros((height, width), dtype=np.float64)
    for index, (r, c) in enumerate(positions, start=1):
        importance[r : r + patch, c : c + patch] += confidence[0] - confidence[index]
        coverage[r : r + patch, c : c + patch] += 1.0
    importance /= np.maximum(coverage, 1.0)
    return {
        "importance": importance,
        "reference_probability": float(reference),
        "patch": patch,
        "stride": stride,
        "evaluations": len(positions) + 1,
    }
