"""Simulated hospital partitions and the local dataset loaders."""

import numpy as np
import pandas as pd
import pytest

from ml.common.datasets import DatasetUnavailableError, load_local_dataset, local_data_summary, save_local_dataset
from ml.ehr.features import EHR_FEATURE_NAMES, NUM_EHR_FEATURES, standardize_ehr
from ml.simulation.hospitals import (
    SIMULATED_HOSPITALS,
    generate_all_hospitals,
    generate_hospital_data,
    generate_reference_cases,
)
from ml.xray.preprocess import block_downsample, prepare_xray


@pytest.fixture(scope="module")
def data_root(tmp_path_factory):
    root = tmp_path_factory.mktemp("hospitals")
    generate_all_hospitals(root, seed=3, scale=0.2)
    return root


def test_there_are_four_hospitals_each_with_three_modalities(data_root):
    assert len(SIMULATED_HOSPITALS) == 4
    for hospital in SIMULATED_HOSPITALS:
        directory = data_root / hospital.hospital_id
        assert sorted(p.name for p in directory.iterdir()) == ["ecg", "ehr", "xray"]
        summary = local_data_summary(directory)
        assert set(summary) == {"ehr", "ecg", "xray"}
        for entry in summary.values():
            assert entry["simulated"] is True and entry["source"] == "simulated"
            assert entry["train_samples"] > entry["val_samples"] > 0


def test_loaded_shapes_and_label_ranges(data_root):
    directory = data_root / "hospital_a"
    ehr = load_local_dataset(directory, "ehr", "train")
    assert ehr.X.shape[1] == NUM_EHR_FEATURES and ehr.feature_names == EHR_FEATURE_NAMES
    assert set(np.unique(ehr.y)) <= {0, 1} and ehr.is_simulated
    ecg = load_local_dataset(directory, "ecg", "train")
    assert ecg.X.shape[1] == 187 and set(np.unique(ecg.y)) <= {0, 1, 2, 3}
    xray = load_local_dataset(directory, "xray", "val")
    assert xray.X.shape[1:] == (64, 64) and xray.X.dtype == np.uint8
    assert len(xray) == len(xray.y)


def test_generation_is_reproducible_and_partitions_differ(tmp_path, data_root):
    again = tmp_path / "again"
    generate_hospital_data(again, SIMULATED_HOSPITALS[0], seed=3, scale=0.2)
    first = load_local_dataset(data_root / "hospital_a", "ehr", "train")
    second = load_local_dataset(again / "hospital_a", "ehr", "train")
    assert np.array_equal(first.X, second.X) and np.array_equal(first.y, second.y)
    other = load_local_dataset(data_root / "hospital_b", "ehr", "train")
    assert first.X.shape != other.X.shape or not np.array_equal(first.X, other.X)


def test_hospitals_are_not_identically_distributed(data_root):
    """Different sizes and different class balance per hospital (non-IID)."""
    sizes, positives = [], []
    for hospital in SIMULATED_HOSPITALS:
        dataset = load_local_dataset(data_root / hospital.hospital_id, "ecg", "train")
        sizes.append(len(dataset))
        positives.append(float(np.mean(dataset.y != 0)))
    assert len(set(sizes)) == 4
    assert max(positives) - min(positives) > 0.1


def test_existing_data_is_not_overwritten(data_root):
    before = (data_root / "hospital_a" / "ehr" / "train.csv").read_bytes()
    generate_hospital_data(data_root, SIMULATED_HOSPITALS[0], seed=999, scale=0.2)
    assert (data_root / "hospital_a" / "ehr" / "train.csv").read_bytes() == before


def test_missing_data_raises_a_clear_error(tmp_path):
    with pytest.raises(DatasetUnavailableError) as error:
        load_local_dataset(tmp_path / "nowhere", "ehr", "train")
    assert "prepare_real_data" in str(error.value)


def test_ehr_loader_validates_columns_and_missing_values(tmp_path):
    directory = tmp_path / "h"
    X = np.ones((6, NUM_EHR_FEATURES), dtype=np.float32)
    y = np.array([0, 1, 0, 1, 0, 1])
    save_local_dataset(directory, "ehr", (X, y), (X[:2], y[:2]), "custom", "test")
    assert load_local_dataset(directory, "ehr", "train").source == "custom"

    frame = pd.read_csv(directory / "ehr" / "train.csv")
    frame.drop(columns=["lactate"]).to_csv(directory / "ehr" / "train.csv", index=False)
    with pytest.raises(ValueError, match="missing columns"):
        load_local_dataset(directory, "ehr", "train")
    frame.loc[0, "age"] = np.nan
    frame.to_csv(directory / "ehr" / "train.csv", index=False)
    with pytest.raises(ValueError, match="missing values"):
        load_local_dataset(directory, "ehr", "train")


def test_preprocessing_helpers():
    with pytest.raises(ValueError):
        standardize_ehr(np.zeros((2, 3)))
    images = np.full((2, 64, 64), 255, dtype=np.uint8)
    prepared = prepare_xray(images)
    assert prepared.dtype == np.float32 and prepared.max() == 1.0
    assert block_downsample(prepared, 16).shape == (2, 16, 16)


def test_reference_cases_are_separate_from_hospital_data(data_root):
    cases = generate_reference_cases("ehr")
    assert cases["X"].shape == (6, NUM_EHR_FEATURES) and len(cases["background"]) > 20
    hospital = load_local_dataset(data_root / "hospital_a", "ehr", "train").X
    for row in cases["X"]:
        assert not (hospital == row).all(axis=1).any()
    assert generate_reference_cases("ecg")["X"].shape == (4, 187)
    assert generate_reference_cases("xray")["X"].shape == (4, 64, 64)
