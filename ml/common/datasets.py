"""On-disk layout of a hospital's local data and the loaders for it.

Every hospital node owns one directory::

    <hospital_dir>/
        ehr/   train.csv  val.csv  manifest.json
        ecg/   train.npz  val.npz  manifest.json
        xray/  train.npz  val.npz  manifest.json

Only code running *inside the hospital node* reads these files. The
coordinator is never given this path. The simulated generators and the
real-dataset preparation script both write this same layout, so the training
code is identical in demo mode and real mode.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from ml.common.types import MODALITIES, ArrayDataset
from ml.ehr.features import EHR_FEATURE_NAMES, EHR_LABEL_COLUMN

SPLITS = ("train", "val")


class DatasetUnavailableError(FileNotFoundError):
    """The hospital has no local data for the requested modality/split."""


def modality_dir(hospital_dir: Path, modality: str) -> Path:
    if modality not in MODALITIES:
        raise ValueError(f"Unknown modality '{modality}'")
    return Path(hospital_dir) / modality


def _split_path(hospital_dir: Path, modality: str, split: str) -> Path:
    if split not in SPLITS:
        raise ValueError(f"Unknown split '{split}'. Expected one of {SPLITS}")
    extension = "csv" if modality == "ehr" else "npz"
    return modality_dir(hospital_dir, modality) / f"{split}.{extension}"


def read_manifest(hospital_dir: Path, modality: str) -> Optional[dict]:
    path = modality_dir(hospital_dir, modality) / "manifest.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_local_dataset(
    hospital_dir: Path,
    modality: str,
    train: tuple,
    val: tuple,
    source: str,
    description: str,
) -> dict:
    """Write both splits and a manifest. ``train``/``val`` are ``(X, y)`` tuples."""
    directory = modality_dir(hospital_dir, modality)
    directory.mkdir(parents=True, exist_ok=True)
    for split, (X, y) in (("train", train), ("val", val)):
        path = _split_path(hospital_dir, modality, split)
        if modality == "ehr":
            frame = pd.DataFrame(np.asarray(X), columns=EHR_FEATURE_NAMES)
            frame[EHR_LABEL_COLUMN] = np.asarray(y, dtype=np.int64)
            frame.to_csv(path, index=False)
        elif modality == "ecg":
            np.savez_compressed(path, signals=np.asarray(X, dtype=np.float32), labels=np.asarray(y, dtype=np.int64))
        else:
            np.savez_compressed(path, images=np.asarray(X, dtype=np.uint8), labels=np.asarray(y, dtype=np.int64))
    manifest = {
        "modality": modality,
        "source": source,
        "simulated": source == "simulated",
        "description": description,
        "splits": {"train": int(len(train[1])), "val": int(len(val[1]))},
        "written_at": datetime.now(timezone.utc).isoformat(),
    }
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def load_local_dataset(hospital_dir: Path, modality: str, split: str) -> ArrayDataset:
    path = _split_path(hospital_dir, modality, split)
    if not path.exists():
        raise DatasetUnavailableError(
            f"No local {modality.upper()} '{split}' data at {path}. "
            "Generate simulated data or run scripts/prepare_real_data.py (see data/README.md)."
        )
    manifest = read_manifest(hospital_dir, modality) or {}
    source = manifest.get("source", "unknown")
    description = manifest.get("description", "")

    if modality == "ehr":
        frame = pd.read_csv(path)
        missing = [c for c in EHR_FEATURE_NAMES + [EHR_LABEL_COLUMN] if c not in frame.columns]
        if missing:
            raise ValueError(f"{path} is missing columns: {missing}")
        if frame[EHR_FEATURE_NAMES + [EHR_LABEL_COLUMN]].isna().any().any():
            raise ValueError(f"{path} contains missing values; impute or drop them during preparation")
        X = frame[EHR_FEATURE_NAMES].to_numpy(dtype=np.float32)
        y = frame[EHR_LABEL_COLUMN].to_numpy(dtype=np.int64)
        return ArrayDataset(X, y, modality, split, source, list(EHR_FEATURE_NAMES), description)

    with np.load(path, allow_pickle=False) as archive:
        key = "signals" if modality == "ecg" else "images"
        if key not in archive.files or "labels" not in archive.files:
            raise ValueError(f"{path} must contain arrays '{key}' and 'labels'")
        X = np.array(archive[key])
        y = np.array(archive["labels"], dtype=np.int64)
    if len(X) != len(y):
        raise ValueError(f"{path}: {len(X)} inputs but {len(y)} labels")
    return ArrayDataset(X, y, modality, split, source, None, description)


def local_data_summary(hospital_dir: Path) -> dict:
    """Counts and provenance only - the metadata a hospital shares with the coordinator."""
    summary = {}
    for modality in MODALITIES:
        manifest = read_manifest(hospital_dir, modality)
        if manifest is None:
            continue
        summary[modality] = {
            "source": manifest.get("source", "unknown"),
            "simulated": bool(manifest.get("simulated", False)),
            "description": manifest.get("description", ""),
            "train_samples": int(manifest.get("splits", {}).get("train", 0)),
            "val_samples": int(manifest.get("splits", {}).get("val", 0)),
        }
    return summary
