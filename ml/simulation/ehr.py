"""Simulated structured EHR admissions.

SIMULATED DATA. Generated from a hand-written model of how vital signs and
laboratory values relate to a latent illness severity. It contains no real
patient information and must not be used to draw clinical conclusions.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ml.ehr.features import EHR_FEATURE_NAMES


@dataclass(frozen=True)
class EHRProfile:
    """How one hospital's admissions differ from the others (non-IID)."""

    age_mean: float = 62.0
    acuity: float = 0.0  # mean latent severity; a referral centre sees sicker patients
    prior_admission_rate: float = 0.8
    measurement_noise: float = 1.0


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-z))


def simulate_ehr(n: int, rng: np.random.Generator, profile: EHRProfile = EHRProfile()):
    noise = profile.measurement_noise
    age = np.clip(rng.normal(profile.age_mean, 15.0, n), 18, 95)
    sex_male = rng.binomial(1, 0.52, n).astype(float)
    severity = rng.normal(profile.acuity, 1.0, n)

    heart_rate = np.clip(82 + 9.0 * severity + rng.normal(0, 10 * noise, n), 35, 190)
    systolic_bp = np.clip(124 - 8.0 * severity + rng.normal(0, 14 * noise, n), 55, 230)
    resp_rate = np.clip(17.5 + 2.2 * severity + rng.normal(0, 2.5 * noise, n), 6, 50)
    temperature = np.clip(37.0 + 0.25 * severity + rng.normal(0, 0.5 * noise, n), 34.0, 41.5)
    spo2 = np.clip(96.5 - 1.6 * severity + rng.normal(0, 1.6 * noise, n), 70, 100)
    wbc = np.clip(8.8 + 1.8 * severity + rng.normal(0, 2.8 * noise, n), 0.5, 40)
    creatinine = np.clip(1.0 + 0.25 * severity + 0.006 * (age - 60) + rng.normal(0, 0.35 * noise, n), 0.3, 9.0)
    lactate = np.clip(1.5 + 0.6 * np.maximum(severity, 0) + np.abs(rng.normal(0, 0.5 * noise, n)), 0.4, 12.0)
    glucose = np.clip(125 + 12 * severity + rng.normal(0, 35 * noise, n), 50, 450)
    hemoglobin = np.clip(12.8 - 0.4 * severity + rng.normal(0, 1.7 * noise, n), 5, 18)
    prior = rng.poisson(profile.prior_admission_rate, n).astype(float)
    comorbidity = np.clip(np.round(rng.normal(1.8 + 0.035 * (age - 60) + 0.5 * prior, 1.5, n)), 0, 12)

    logit = (
        -2.6
        + 0.028 * (age - 62)
        + 0.022 * (heart_rate - 85)
        - 0.022 * (systolic_bp - 122)
        + 0.10 * (resp_rate - 18)
        + 0.35 * np.abs(temperature - 37.0)
        - 0.14 * (spo2 - 96)
        + 0.04 * (wbc - 9)
        + 0.55 * (creatinine - 1.1)
        + 0.60 * (lactate - 1.7)
        + 0.20 * (comorbidity - 2.5)
        + 0.18 * prior
        + 0.50 * ((lactate > 2.5) & (systolic_bp < 100))
    )
    y = rng.binomial(1, _sigmoid(logit)).astype(np.int64)

    columns = {
        "age": np.round(age),
        "sex_male": sex_male,
        "heart_rate": np.round(heart_rate),
        "systolic_bp": np.round(systolic_bp),
        "resp_rate": np.round(resp_rate),
        "temperature_c": np.round(temperature, 1),
        "spo2": np.round(spo2),
        "wbc": np.round(wbc, 1),
        "creatinine": np.round(creatinine, 2),
        "lactate": np.round(lactate, 1),
        "glucose": np.round(glucose),
        "hemoglobin": np.round(hemoglobin, 1),
        "prior_admissions_12m": prior,
        "comorbidity_index": comorbidity,
    }
    X = np.column_stack([columns[name] for name in EHR_FEATURE_NAMES]).astype(np.float32)
    return X, y
