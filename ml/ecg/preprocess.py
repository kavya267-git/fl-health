"""ECG beat preprocessing shared by every backend."""

from __future__ import annotations

import numpy as np

#: Samples per beat window. Matches the widely used MIT-BIH heartbeat export
#: (187 samples at 125 Hz), so real data can be dropped in without resampling.
ECG_BEAT_LENGTH = 187
ECG_SAMPLE_RATE_HZ = 125


def prepare_ecg(X: np.ndarray) -> np.ndarray:
    """Return float32 beats of shape [n, ECG_BEAT_LENGTH], clipped to a sane range."""
    X = np.asarray(X, dtype=np.float32)
    if X.ndim == 3 and X.shape[1] == 1:
        X = X[:, 0, :]
    if X.ndim != 2 or X.shape[1] != ECG_BEAT_LENGTH:
        raise ValueError(f"ECG input must have shape [n, {ECG_BEAT_LENGTH}], got {X.shape}")
    return np.clip(X, -5.0, 5.0)
