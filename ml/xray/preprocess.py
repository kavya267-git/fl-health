"""Chest-image preprocessing shared by every backend."""

from __future__ import annotations

import numpy as np


def prepare_xray(X: np.ndarray) -> np.ndarray:
    """Return float32 images of shape [n, H, W] scaled to [0, 1]."""
    X = np.asarray(X)
    if X.ndim == 4 and X.shape[1] == 1:
        X = X[:, 0]
    if X.ndim != 3:
        raise ValueError(f"X-ray input must have shape [n, H, W], got {X.shape}")
    if X.dtype == np.uint8:
        return X.astype(np.float32) / 255.0
    X = X.astype(np.float32)
    if X.size and float(X.max()) > 1.5:  # 0-255 floats
        X = X / 255.0
    return np.clip(X, 0.0, 1.0)


def block_downsample(images: np.ndarray, size: int) -> np.ndarray:
    """Average-pool [n, H, W] images down to [n, size, size]."""
    n, height, width = images.shape
    if height % size or width % size:
        raise ValueError(f"Image size {height}x{width} is not divisible by {size}")
    fh, fw = height // size, width // size
    return images.reshape(n, size, fh, size, fw).mean(axis=(2, 4))
