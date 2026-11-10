"""EHR feature schema.

Standardisation uses fixed clinical reference values rather than statistics
computed from data. That keeps preprocessing identical at every hospital
without any hospital having to share (or the coordinator having to pool)
per-feature means and variances.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

import numpy as np


@dataclass(frozen=True)
class EHRFeature:
    name: str
    label: str
    unit: str
    ref_mean: float
    ref_std: float
    description: str


EHR_FEATURES: List[EHRFeature] = [
    EHRFeature("age", "Age", "years", 62.0, 16.0, "Age at admission."),
    EHRFeature("sex_male", "Sex (male)", "0/1", 0.5, 0.5, "1 if recorded sex is male."),
    EHRFeature("heart_rate", "Heart rate", "bpm", 85.0, 16.0, "First recorded heart rate."),
    EHRFeature("systolic_bp", "Systolic blood pressure", "mmHg", 122.0, 20.0, "First recorded systolic pressure."),
    EHRFeature("resp_rate", "Respiratory rate", "breaths/min", 18.0, 4.5, "First recorded respiratory rate."),
    EHRFeature("temperature_c", "Temperature", "°C", 37.0, 0.7, "First recorded body temperature."),
    EHRFeature("spo2", "Oxygen saturation", "%", 96.0, 3.0, "First recorded SpO2."),
    EHRFeature("wbc", "White blood cell count", "10⁹/L", 9.0, 4.0, "First white blood cell count."),
    EHRFeature("creatinine", "Creatinine", "mg/dL", 1.1, 0.6, "First serum creatinine."),
    EHRFeature("lactate", "Lactate", "mmol/L", 1.7, 1.1, "First serum lactate."),
    EHRFeature("glucose", "Glucose", "mg/dL", 130.0, 45.0, "First blood glucose."),
    EHRFeature("hemoglobin", "Haemoglobin", "g/dL", 12.5, 2.0, "First haemoglobin."),
    EHRFeature(
        "prior_admissions_12m",
        "Admissions in prior 12 months",
        "count",
        0.8,
        1.2,
        "Earlier admissions in the last year.",
    ),
    EHRFeature("comorbidity_index", "Comorbidity index", "score", 2.5, 2.0, "Charlson-style comorbidity burden."),
]

EHR_FEATURE_NAMES: List[str] = [feature.name for feature in EHR_FEATURES]
EHR_LABEL_COLUMN = "label"
NUM_EHR_FEATURES = len(EHR_FEATURES)

_REF_MEAN = np.array([f.ref_mean for f in EHR_FEATURES], dtype=np.float32)
_REF_STD = np.array([f.ref_std for f in EHR_FEATURES], dtype=np.float32)
#: (centre, spread) per feature, the fixed reference values above; also used for imputation distances.
EHR_REFERENCE_SCALE = (_REF_MEAN, _REF_STD)


def standardize_ehr(X: np.ndarray) -> np.ndarray:
    """Scale raw feature values by the fixed clinical reference mean and spread."""
    X = np.asarray(X, dtype=np.float32)
    if X.ndim != 2 or X.shape[1] != NUM_EHR_FEATURES:
        raise ValueError(f"EHR input must have shape [n, {NUM_EHR_FEATURES}], got {X.shape}")
    return np.clip((X - _REF_MEAN) / _REF_STD, -6.0, 6.0)


def feature_metadata() -> List[dict]:
    return [{"name": f.name, "label": f.label, "unit": f.unit, "description": f.description} for f in EHR_FEATURES]
