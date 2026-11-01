"""Preparation of real datasets into hospital partitions (run on small files in the real formats)."""

import numpy as np
import pandas as pd
import pytest

from ml.common.datasets import load_local_dataset
from ml.common.real_data import (
    partition_groups,
    prepare_chestxray14,
    prepare_ecg_heartbeat_csv,
    prepare_ehr_csv,
    split_train_val,
)
from ml.ehr.features import EHR_FEATURE_NAMES
from ml.simulation.ecg import simulate_ecg
from ml.simulation.ehr import simulate_ehr

HOSPITALS = ["hospital_a", "hospital_b", "hospital_c", "hospital_d"]


def test_every_group_lands_in_exactly_one_hospital():
    rng = np.random.default_rng(0)
    groups = rng.integers(0, 60, size=600)
    labels = (groups % 2).astype(int)  # label is a property of the group (patient)
    parts = partition_groups(groups, labels, HOSPITALS, rng, alpha=0.5)
    assert sorted(np.concatenate(list(parts.values())).tolist()) == list(range(600))
    owners = {}
    for hospital, rows in parts.items():
        for group in set(groups[rows].tolist()):
            assert owners.setdefault(group, hospital) == hospital


def test_low_alpha_gives_more_label_skew_than_an_even_split():
    labels = np.repeat([0, 1], 2000)
    groups = np.arange(4000)

    def spread(alpha, seed):
        parts = partition_groups(groups, labels, HOSPITALS, np.random.default_rng(seed), alpha)
        shares = [labels[rows].mean() for rows in parts.values() if len(rows)]
        return max(shares) - min(shares)

    skewed = np.mean([spread(0.2, seed) for seed in range(8)])
    even = np.mean([spread(None, seed) for seed in range(8)])
    assert skewed > even + 0.2


def test_train_val_split_keeps_groups_together():
    groups = np.repeat(np.arange(20), 5)
    train, val = split_train_val(groups, np.random.default_rng(0), 0.25)
    assert len(train) + len(val) == 100 and len(val) == 25
    assert not set(groups[train]) & set(groups[val])


def test_prepare_ehr_csv_with_column_mapping_and_patient_groups(tmp_path):
    X, y = simulate_ehr(400, np.random.default_rng(0))
    frame = pd.DataFrame(X, columns=EHR_FEATURE_NAMES).rename(columns={"age": "anchor_age"})
    frame["hospital_expire_flag"] = y
    frame["subject_id"] = np.random.default_rng(1).integers(0, 150, size=400)
    frame.loc[3, "lactate"] = np.nan
    csv = tmp_path / "admissions.csv"
    frame.to_csv(csv, index=False)

    manifests = prepare_ehr_csv(
        csv,
        tmp_path / "hospitals",
        HOSPITALS,
        column_mapping={"anchor_age": "age"},
        label_column="hospital_expire_flag",
        group_column="subject_id",
        alpha=None,
    )
    assert set(manifests) == set(HOSPITALS)
    total = sum(m["splits"]["train"] + m["splits"]["val"] for m in manifests.values())
    assert total == 399  # the row with a missing value was dropped
    assert "1 row(s) with missing values dropped" in manifests["hospital_a"]["description"]
    dataset = load_local_dataset(tmp_path / "hospitals" / "hospital_a", "ehr", "train")
    assert dataset.source == "mimic-iv" and not dataset.is_simulated
    assert dataset.X.shape[1] == 14


def test_prepare_ehr_csv_reports_missing_columns(tmp_path):
    csv = tmp_path / "bad.csv"
    pd.DataFrame({"age": [50, 60], "label": [0, 1]}).to_csv(csv, index=False)
    with pytest.raises(ValueError, match="missing required columns"):
        prepare_ehr_csv(csv, tmp_path / "hospitals", HOSPITALS)


def test_prepare_ecg_heartbeat_export_drops_class_q(tmp_path):
    signals, labels = simulate_ecg(300, np.random.default_rng(0))
    labels = labels.copy()
    labels[:10] = 4  # the export's fifth class, which this task does not use
    table = np.column_stack([signals, labels.astype(float)])
    csv = tmp_path / "mitbih_train.csv"
    pd.DataFrame(table).to_csv(csv, index=False, header=False)

    manifests = prepare_ecg_heartbeat_csv([csv], tmp_path / "hospitals", HOSPITALS, alpha=None)
    total = sum(m["splits"]["train"] + m["splits"]["val"] for m in manifests.values())
    assert total == 290
    dataset = load_local_dataset(tmp_path / "hospitals" / "hospital_b", "ecg", "val")
    assert dataset.X.shape[1] == 187 and dataset.y.max() <= 3 and dataset.source == "mit-bih"
    with pytest.raises(ValueError, match="Expected 188 columns"):
        bad = tmp_path / "bad.csv"
        pd.DataFrame(np.zeros((3, 10))).to_csv(bad, index=False, header=False)
        prepare_ecg_heartbeat_csv([bad], tmp_path / "hospitals", HOSPITALS)


def test_prepare_chestxray14_groups_by_patient_and_resizes(tmp_path):
    from PIL import Image

    image_dir = tmp_path / "images"
    image_dir.mkdir()
    rng = np.random.default_rng(0)
    rows = []
    for index in range(80):
        name = f"{index:08d}_000.png"
        Image.fromarray(rng.integers(0, 255, size=(100, 120), dtype=np.uint8)).save(image_dir / name)
        rows.append(
            {
                "Image Index": name,
                "Finding Labels": "No Finding" if index % 3 else "Effusion|Mass",
                "Patient ID": index // 2,
            }
        )
    rows.append({"Image Index": "missing.png", "Finding Labels": "Mass", "Patient ID": 999})
    entries = tmp_path / "Data_Entry_2017.csv"
    pd.DataFrame(rows).to_csv(entries, index=False)

    manifests = prepare_chestxray14(entries, image_dir, tmp_path / "hospitals", HOSPITALS, image_size=32, alpha=None)
    assert sum(m["splits"]["train"] + m["splits"]["val"] for m in manifests.values()) == 80
    dataset = load_local_dataset(tmp_path / "hospitals" / "hospital_a", "xray", "train")
    assert dataset.X.shape[1:] == (32, 32) and dataset.X.dtype == np.uint8
    assert set(np.unique(dataset.y)) <= {0, 1} and dataset.source == "nih-chestxray14"
    with pytest.raises(ValueError, match="No images"):
        prepare_chestxray14(entries, tmp_path / "nowhere", tmp_path / "hospitals", HOSPITALS)
