"""Local data check, run by a hospital node on its own machine before it connects.

For each modality the hospital declared, it opens the prepared folder (the layout
``scripts/prepare_real_data.py`` writes, see ``ml/common/datasets.py``) and checks
columns, types, value ranges, record counts and the label set. The result per
modality is pass / fail, record counts, label counts and short problem
descriptions. That summary, and nothing from the records themselves, is what
the node reports to the coordinator.

The ranges are wide plausibility bounds meant to catch unit mix-ups and
corrupted files (for example temperature in Fahrenheit, or blood pressure in
kPa). They are not clinical reference ranges.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List

import numpy as np

from ml.common.datasets import DatasetUnavailableError, load_local_dataset
from ml.ecg.preprocess import ECG_BEAT_LENGTH
from ml.ehr.features import EHR_FEATURE_NAMES

#: Fewer training records than this cannot train (batch normalisation needs batches of 2+).
MIN_TRAIN_RECORDS = 8
MIN_VAL_RECORDS = 1
#: A feature with a larger share of missing training values fails (KNN imputation needs neighbours).
MAX_MISSING_SHARE = 0.5

#: (low, high) plausibility bounds per EHR feature, in the units of ml/ehr/features.py.
EHR_BOUNDS: Dict[str, tuple] = {
    "age": (0, 120),
    "sex_male": (0, 1),
    "heart_rate": (20, 250),
    "systolic_bp": (40, 300),
    "resp_rate": (4, 80),
    "temperature_c": (30, 45),
    "spo2": (50, 100),
    "wbc": (0, 200),
    "creatinine": (0, 30),
    "lactate": (0, 30),
    "glucose": (10, 2000),
    "hemoglobin": (2, 25),
    "prior_admissions_12m": (0, 100),
    "comorbidity_index": (0, 40),
}
LABELS = {"ehr": (0, 1), "ecg": (0, 1, 2, 3), "xray": (0, 1)}
LABEL_NAMES = {
    "ehr": ("no adverse outcome", "adverse outcome"),
    "ecg": ("N", "S", "V", "F"),
    "xray": ("no finding", "finding"),
}


def _labels(modality: str, y: np.ndarray, split: str, problems: List[str]) -> Dict[str, int]:
    allowed = set(LABELS[modality])
    found = set(np.unique(y).tolist())
    if found - allowed:
        problems.append(f"{split}: labels {sorted(found - allowed)} are not allowed; use {sorted(allowed)}")
    return {LABEL_NAMES[modality][k]: int(np.sum(y == k)) for k in LABELS[modality]}


def _check_values(modality: str, X: np.ndarray, split: str, problems: List[str]) -> None:
    if modality == "ehr":
        missing = np.isnan(X)
        for i, name in enumerate(EHR_FEATURE_NAMES):
            column = X[:, i]
            share = float(missing[:, i].mean()) if len(column) else 0.0
            if split == "train" and share > MAX_MISSING_SHARE:
                problems.append(f"{split}: '{name}' is missing in {share:.0%} of records (at most {MAX_MISSING_SHARE:.0%})")
            low, high = EHR_BOUNDS[name]
            present = column[~missing[:, i]]
            outside = int(np.sum((present < low) | (present > high)))
            if outside:
                problems.append(f"{split}: {outside} value(s) of '{name}' outside {low}-{high}; check the units")
    elif modality == "ecg":
        if X.ndim != 2 or X.shape[1] != ECG_BEAT_LENGTH:
            problems.append(f"{split}: each beat must have {ECG_BEAT_LENGTH} samples (125 Hz); got shape {X.shape}")
        elif not np.all(np.isfinite(X)):
            problems.append(f"{split}: beats contain NaN or infinite samples")
    else:
        if X.ndim != 3:
            problems.append(f"{split}: images must have shape [n, height, width]; got {X.shape}")
        elif X.dtype != np.uint8:
            problems.append(f"{split}: images must be 8-bit greyscale (uint8); got {X.dtype}")
        elif X.shape[1] < 32 or X.shape[2] < 32:
            problems.append(f"{split}: images are {X.shape[1]}x{X.shape[2]} pixels; at least 32x32 is needed")


def check_modality(data_dir: Path, modality: str) -> dict:
    """Pass / fail, counts and problems for one modality. Reads only this machine's files."""
    problems: List[str] = []
    counts = {"train": 0, "val": 0}
    label_counts: Dict[str, int] = {}
    for split in ("train", "val"):
        try:
            dataset = load_local_dataset(Path(data_dir), modality, split, allow_missing_features=(modality == "ehr"))
        except DatasetUnavailableError:
            problems.append(f"{split}: no file found (expected the layout written by scripts/prepare_real_data.py)")
            continue
        except (ValueError, KeyError, OSError) as exc:
            problems.append(f"{split}: cannot be read: {str(exc)[:160]}")
            continue
        counts[split] = len(dataset)
        X = np.asarray(dataset.X)
        if modality == "ehr":
            X = X.astype(np.float64)
        _check_values(modality, X, split, problems)
        labels = _labels(modality, np.asarray(dataset.y), split, problems)
        if split == "train":
            label_counts = labels
            if sum(1 for v in labels.values() if v) < 2:
                problems.append("train: at least two different labels are needed to train a classifier")
    if counts["train"] < MIN_TRAIN_RECORDS:
        problems.append(f"train: {counts['train']} record(s); at least {MIN_TRAIN_RECORDS} are needed")
    if counts["val"] < MIN_VAL_RECORDS:
        problems.append(f"held-out: {counts['val']} record(s); at least {MIN_VAL_RECORDS} is needed")
    return {
        "passed": not problems,
        "train_records": counts["train"],
        "val_records": counts["val"],
        "label_counts": label_counts,
        "problems": problems[:10],
    }


def check_folder(data_dir: Path, modalities: Iterable[str]) -> Dict[str, dict]:
    return {modality: check_modality(data_dir, modality) for modality in modalities}
