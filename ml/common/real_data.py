"""Turn real datasets into the per-hospital layout used by the hospital nodes.

Nothing here downloads data. MIMIC-IV, MIT-BIH and NIH ChestX-ray14 each have
their own access terms; obtain them yourself and point these functions at the
files. Each function reads a commonly used export of the dataset, splits it
into hospital partitions, and writes ``<data_root>/<hospital_id>/<modality>/``.

Records that belong to the same patient are always kept together - in one
hospital and on one side of the train/validation split - whenever a patient
identifier is available.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from ml.common.datasets import save_local_dataset
from ml.ecg.preprocess import ECG_BEAT_LENGTH
from ml.ehr.features import EHR_FEATURE_NAMES, EHR_LABEL_COLUMN

DEFAULT_HOSPITALS = ("hospital_a", "hospital_b", "hospital_c", "hospital_d")


def partition_groups(
    groups: np.ndarray,
    labels: np.ndarray,
    hospital_ids: Sequence[str],
    rng: np.random.Generator,
    alpha: Optional[float] = 1.0,
) -> Dict[str, np.ndarray]:
    """Assign every group (patient) to exactly one hospital.

    ``alpha`` is the Dirichlet concentration that controls how unevenly labels
    are spread across hospitals: small values (0.3) give strongly non-IID
    partitions, large values (100) give nearly identical ones. ``None`` deals
    groups out evenly at random.
    Returns ``{hospital_id: row indices}``.
    """
    groups = np.asarray(groups)
    labels = np.asarray(labels)
    unique_groups, first_index = np.unique(groups, return_index=True)
    group_label = labels[first_index]
    assignment = np.empty(len(unique_groups), dtype=np.int64)
    n_hospitals = len(hospital_ids)

    if alpha is None:
        order = rng.permutation(len(unique_groups))
        assignment[order] = np.arange(len(unique_groups)) % n_hospitals
    else:
        for label in np.unique(group_label):
            members = rng.permutation(np.where(group_label == label)[0])
            shares = rng.dirichlet(np.full(n_hospitals, alpha))
            cuts = (np.cumsum(shares)[:-1] * len(members)).astype(int)
            for hospital_index, chunk in enumerate(np.split(members, cuts)):
                assignment[chunk] = hospital_index

    hospital_of_group = dict(zip(unique_groups.tolist(), assignment.tolist()))
    row_hospital = np.array([hospital_of_group[g] for g in groups.tolist()])
    return {hospital_id: np.where(row_hospital == index)[0] for index, hospital_id in enumerate(hospital_ids)}


def split_train_val(groups: np.ndarray, rng: np.random.Generator, val_fraction: float = 0.25):
    """Row indices for train and validation, keeping each group on one side."""
    unique_groups = rng.permutation(np.unique(groups))
    n_val = max(1, int(round(len(unique_groups) * val_fraction))) if len(unique_groups) > 1 else 0
    val_groups = set(unique_groups[:n_val].tolist())
    is_val = np.array([g in val_groups for g in groups.tolist()])
    return np.where(~is_val)[0], np.where(is_val)[0]


def _write_partitions(
    data_root: Path,
    modality: str,
    X: np.ndarray,
    y: np.ndarray,
    groups: np.ndarray,
    hospital_ids: Sequence[str],
    source: str,
    description: str,
    seed: int,
    alpha: Optional[float],
    val_fraction: float,
) -> Dict[str, dict]:
    rng = np.random.default_rng(seed)
    manifests = {}
    for hospital_id, rows in partition_groups(groups, y, hospital_ids, rng, alpha).items():
        if len(rows) < 4:
            raise ValueError(
                f"{hospital_id} would receive only {len(rows)} {modality} record(s). "
                "Use a larger dataset, fewer hospitals or a larger alpha."
            )
        train, val = split_train_val(groups[rows], rng, val_fraction)
        if len(train) < 2 or len(val) < 1:
            raise ValueError(f"{hospital_id} does not have enough {modality} records for a train/validation split.")
        manifests[hospital_id] = save_local_dataset(
            Path(data_root) / hospital_id,
            modality,
            train=(X[rows][train], y[rows][train]),
            val=(X[rows][val], y[rows][val]),
            source=source,
            description=description,
        )
    return manifests


def prepare_ehr_csv(
    csv_path: Path,
    data_root: Path,
    hospital_ids: Sequence[str] = DEFAULT_HOSPITALS,
    column_mapping: Optional[Dict[str, str]] = None,
    label_column: str = EHR_LABEL_COLUMN,
    group_column: Optional[str] = None,
    source: str = "mimic-iv",
    seed: int = 0,
    alpha: Optional[float] = 1.0,
    val_fraction: float = 0.25,
    keep_missing: bool = False,
) -> Dict[str, dict]:
    """Partition a tabular extract (for example one row per MIMIC-IV admission).

    The CSV must provide the 14 features in ``ml.ehr.features`` and a binary
    label. ``column_mapping`` renames your columns to those feature names
    (``{"your_column": "feature_name"}``). Rows with missing values are dropped
    and counted in the description, unless ``keep_missing`` is set: then rows
    with missing *feature* values are kept and each hospital node fills them in
    by KNN imputation fitted on its own training split (``ml.ehr.imputation``).
    Rows without a label are always dropped.
    """
    frame = pd.read_csv(csv_path)
    if column_mapping:
        frame = frame.rename(columns=column_mapping)
    if label_column != EHR_LABEL_COLUMN:
        frame = frame.rename(columns={label_column: EHR_LABEL_COLUMN})
    missing = [c for c in EHR_FEATURE_NAMES + [EHR_LABEL_COLUMN] if c not in frame.columns]
    if missing:
        raise ValueError(f"{csv_path} is missing required columns: {missing}")
    if group_column and group_column not in frame.columns:
        raise ValueError(f"Group column '{group_column}' is not in {csv_path}")

    keep = EHR_FEATURE_NAMES + [EHR_LABEL_COLUMN] + ([group_column] if group_column else [])
    before = len(frame)
    frame = frame[keep]
    frame = (frame.dropna(subset=[EHR_LABEL_COLUMN]) if keep_missing else frame.dropna()).reset_index(drop=True)
    dropped = before - len(frame)
    gaps = int(frame[EHR_FEATURE_NAMES].isna().sum().sum())
    labels = frame[EHR_LABEL_COLUMN].to_numpy()
    if not set(np.unique(labels)) <= {0, 1}:
        raise ValueError("The EHR label must be binary (0 or 1)")
    groups = frame[group_column].to_numpy() if group_column else np.arange(len(frame))
    return _write_partitions(
        data_root,
        "ehr",
        frame[EHR_FEATURE_NAMES].to_numpy(dtype=np.float32),
        labels.astype(np.int64),
        groups,
        hospital_ids,
        source,
        (
            f"Prepared from {Path(csv_path).name}; {dropped} row(s) without a label dropped; {gaps} missing "
            "feature value(s) kept for KNN imputation at the hospital node."
            if keep_missing
            else f"Prepared from {Path(csv_path).name}; {dropped} row(s) with missing values dropped."
        ),
        seed,
        alpha,
        val_fraction,
    )


def prepare_ecg_heartbeat_csv(
    csv_paths: Sequence[Path],
    data_root: Path,
    hospital_ids: Sequence[str] = DEFAULT_HOSPITALS,
    source: str = "mit-bih",
    seed: int = 0,
    alpha: Optional[float] = 1.0,
    val_fraction: float = 0.25,
) -> Dict[str, dict]:
    """Partition the MIT-BIH "heartbeat" CSV export (187 samples + class per row, no header).

    That export uses five AAMI classes: 0 N, 1 S, 2 V, 3 F, 4 Q. This project's
    ECG task has four classes (N, S, V, F), so class 4 (unclassifiable / paced)
    rows are dropped. The export has no patient identifiers, so beats cannot be
    grouped by patient; the description records that limitation.
    """
    frames = [pd.read_csv(path, header=None) for path in csv_paths]
    table = pd.concat(frames, ignore_index=True)
    if table.shape[1] != ECG_BEAT_LENGTH + 1:
        raise ValueError(
            f"Expected {ECG_BEAT_LENGTH + 1} columns ({ECG_BEAT_LENGTH} samples and a class), got {table.shape[1]}"
        )
    labels = table.iloc[:, -1].to_numpy().astype(np.int64)
    keep = labels <= 3
    signals = table.iloc[:, :-1].to_numpy(dtype=np.float32)[keep]
    labels = labels[keep]
    return _write_partitions(
        data_root,
        "ecg",
        signals,
        labels,
        np.arange(len(labels)),
        hospital_ids,
        source,
        f"MIT-BIH heartbeat export; {int((~keep).sum())} class-Q beats dropped; "
        "beats are not grouped by patient (the export has no patient ids).",
        seed,
        alpha,
        val_fraction,
    )


def prepare_chestxray14(
    entries_csv: Path,
    image_dir: Path,
    data_root: Path,
    hospital_ids: Sequence[str] = DEFAULT_HOSPITALS,
    image_size: int = 224,
    limit: Optional[int] = None,
    source: str = "nih-chestxray14",
    seed: int = 0,
    alpha: Optional[float] = 1.0,
    val_fraction: float = 0.25,
) -> Dict[str, dict]:
    """Partition NIH ChestX-ray14 using its ``Data_Entry_2017.csv`` index.

    Label: 0 if "Finding Labels" is "No Finding", otherwise 1. Images are
    converted to 8-bit greyscale and resized to ``image_size``. All images of a
    patient go to the same hospital and the same split. ``limit`` caps the
    number of images (taken in file order) for a quick trial run.
    """
    from PIL import Image

    entries = pd.read_csv(entries_csv)
    required = ["Image Index", "Finding Labels", "Patient ID"]
    missing = [c for c in required if c not in entries.columns]
    if missing:
        raise ValueError(f"{entries_csv} is missing columns: {missing}")
    image_dir = Path(image_dir)
    entries = entries[[(image_dir / name).exists() for name in entries["Image Index"]]]
    if limit:
        entries = entries.head(limit)
    if entries.empty:
        raise ValueError(f"No images listed in {entries_csv} were found in {image_dir}")

    images: List[np.ndarray] = []
    for name in entries["Image Index"]:
        with Image.open(image_dir / name) as image:
            images.append(np.asarray(image.convert("L").resize((image_size, image_size)), dtype=np.uint8))
    labels = (entries["Finding Labels"].to_numpy() != "No Finding").astype(np.int64)
    return _write_partitions(
        data_root,
        "xray",
        np.stack(images),
        labels,
        entries["Patient ID"].to_numpy(),
        hospital_ids,
        source,
        f"NIH ChestX-ray14, {image_size}x{image_size} greyscale, finding vs no finding, grouped by patient.",
        seed,
        alpha,
        val_fraction,
    )
