"""Simulated single-beat ECG windows.

SIMULATED DATA. Each beat is a sum of Gaussian bumps standing in for the P, Q,
R, S and T waves, with class-dependent changes that mimic textbook morphology
(early beat with abnormal P for supraventricular ectopy; wide QRS, no P and an
inverted T for ventricular ectopy; a blend of normal and ventricular for
fusion). These are cartoons of real rhythms, not recordings.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from ml.ecg.preprocess import ECG_BEAT_LENGTH

ECG_CLASSES = ("N", "S", "V", "F")


@dataclass(frozen=True)
class ECGProfile:
    class_mix: Sequence[float] = (0.70, 0.10, 0.15, 0.05)
    noise: float = 0.04  # sensor noise standard deviation
    gain: float = 1.0  # device amplitude calibration
    wander: float = 0.05  # baseline wander amplitude


def _wave(t: np.ndarray, amplitude: float, centre: float, width: float) -> np.ndarray:
    return amplitude * np.exp(-0.5 * ((t - centre) / width) ** 2)


def _normal_beat(t, rng, shift=0.0, p_amplitude=None):
    p_amp = rng.normal(0.15, 0.02) if p_amplitude is None else p_amplitude
    r_centre = 0.30 + shift + rng.normal(0, 0.006)
    return (
        _wave(t, p_amp, r_centre - 0.13 + rng.normal(0, 0.005), 0.025)
        + _wave(t, rng.normal(-0.12, 0.02), r_centre - 0.025, 0.008)
        + _wave(t, rng.normal(1.0, 0.07), r_centre, 0.012 * rng.uniform(0.9, 1.15))
        + _wave(t, rng.normal(-0.25, 0.04), r_centre + 0.025, 0.010)
        + _wave(t, rng.normal(0.30, 0.04), r_centre + 0.22 + rng.normal(0, 0.01), 0.045)
    )


def _ventricular_beat(t, rng):
    r_centre = 0.29 + rng.normal(0, 0.008)
    widen = rng.uniform(2.6, 3.6)
    return (
        _wave(t, rng.normal(1.15, 0.10), r_centre, 0.012 * widen)
        + _wave(t, rng.normal(-0.55, 0.08), r_centre + 0.075, 0.030)
        + _wave(t, rng.normal(-0.35, 0.05), r_centre + 0.27 + rng.normal(0, 0.012), 0.055)
    )


def _beat(label: int, t: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    if label == 0:  # normal
        return _normal_beat(t, rng)
    if label == 1:  # supraventricular ectopic: premature, abnormal or absent P wave
        return _normal_beat(t, rng, shift=-rng.uniform(0.035, 0.07), p_amplitude=rng.normal(-0.05, 0.04))
    if label == 2:  # ventricular ectopic
        return _ventricular_beat(t, rng)
    blend = rng.uniform(0.35, 0.65)  # fusion of a normal and a ventricular beat
    return blend * _normal_beat(t, rng) + (1 - blend) * _ventricular_beat(t, rng)


def simulate_ecg(n: int, rng: np.random.Generator, profile: ECGProfile = ECGProfile()):
    mix = np.asarray(profile.class_mix, dtype=float)
    mix = mix / mix.sum()
    labels = rng.choice(len(ECG_CLASSES), size=n, p=mix).astype(np.int64)
    t = np.linspace(0.0, 1.0, ECG_BEAT_LENGTH, endpoint=False)
    signals = np.empty((n, ECG_BEAT_LENGTH), dtype=np.float32)
    for index, label in enumerate(labels):
        beat = _beat(int(label), t, rng)
        wander = profile.wander * np.sin(2 * np.pi * (rng.uniform(0.3, 1.2) * t + rng.uniform()))
        noise = rng.normal(0, profile.noise, ECG_BEAT_LENGTH)
        signals[index] = (profile.gain * beat + wander + noise).astype(np.float32)
    return signals, labels
