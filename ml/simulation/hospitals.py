"""The four simulated hospitals and their local data partitions.

SIMULATED. The hospitals, their names and all of their data are fictional.
Each hospital gets a different size and a different data distribution so the
federation is non-IID, as it would be between real institutions.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import numpy as np

from ml.common.datasets import read_manifest, save_local_dataset
from ml.common.types import MODALITIES
from ml.simulation.ecg import ECGProfile, simulate_ecg
from ml.simulation.ehr import EHRProfile, simulate_ehr
from ml.simulation.xray import XrayProfile, simulate_xray

VAL_FRACTION = 0.25


@dataclass(frozen=True)
class SimulatedHospital:
    hospital_id: str
    name: str
    kind: str
    sizes: Dict[str, int]  # total records per modality (train + validation)
    ehr: EHRProfile = field(default_factory=EHRProfile)
    ecg: ECGProfile = field(default_factory=ECGProfile)
    xray: XrayProfile = field(default_factory=XrayProfile)


SIMULATED_HOSPITALS: List[SimulatedHospital] = [
    SimulatedHospital(
        "hospital_a",
        "Northfield General Hospital",
        "Teaching hospital",
        {"ehr": 1200, "ecg": 640, "xray": 320},
        EHRProfile(age_mean=63, acuity=0.25, prior_admission_rate=1.0),
        ECGProfile(class_mix=(0.70, 0.10, 0.15, 0.05), noise=0.035, gain=1.0),
        XrayProfile(prevalence=0.45, contrast=1.0, brightness=0.0),
    ),
    SimulatedHospital(
        "hospital_b",
        "Riverside Medical Centre",
        "Regional hospital",
        {"ehr": 920, "ecg": 520, "xray": 260},
        EHRProfile(age_mean=58, acuity=0.0, prior_admission_rate=0.7),
        ECGProfile(class_mix=(0.55, 0.20, 0.20, 0.05), noise=0.05, gain=0.9),
        XrayProfile(prevalence=0.35, contrast=0.9, brightness=0.03),
    ),
    SimulatedHospital(
        "hospital_c",
        "St. Elara Community Hospital",
        "Community hospital",
        {"ehr": 680, "ecg": 420, "xray": 220},
        EHRProfile(age_mean=68, acuity=-0.2, prior_admission_rate=0.9, measurement_noise=1.15),
        ECGProfile(class_mix=(0.80, 0.05, 0.10, 0.05), noise=0.06, gain=1.1),
        XrayProfile(prevalence=0.30, contrast=1.1, brightness=-0.03, noise=0.045),
    ),
    SimulatedHospital(
        "hospital_d",
        "Harbourview Clinic",
        "Specialist cardiac clinic",
        {"ehr": 520, "ecg": 360, "xray": 200},
        EHRProfile(age_mean=60, acuity=0.45, prior_admission_rate=1.3),
        ECGProfile(class_mix=(0.50, 0.15, 0.25, 0.10), noise=0.04, gain=1.0),
        XrayProfile(prevalence=0.50, contrast=0.95, brightness=0.02),
    ),
]

_DESCRIPTIONS = {
    "ehr": "Simulated structured admissions (14 features, binary outcome). Not real patient data.",
    "ecg": "Simulated single-beat ECG windows (187 samples, 4 AAMI-style classes). Not real recordings.",
    "xray": "Simulated 64x64 chest phantoms (finding / no finding). Not real radiographs.",
}


def sample_hospital(hospital_id: str, name: str, sizes: Optional[Dict[str, int]] = None) -> SimulatedHospital:
    """A SIMULATED profile for any hospital id (the agent's "Use sample data"): fictional records, default mix."""
    default = {"ehr": 600, "ecg": 400, "xray": 200}
    chosen = {m: max(40, min(int((sizes or {}).get(m, default[m])), default[m] * 2)) for m in default}
    return SimulatedHospital(hospital_id, name, "Sample data (SIMULATED)", chosen)


def get_simulated_hospital(hospital_id: str) -> SimulatedHospital:
    for hospital in SIMULATED_HOSPITALS:
        if hospital.hospital_id == hospital_id:
            return hospital
    raise KeyError(f"No simulated hospital '{hospital_id}'")


def _rng(seed: int, hospital_id: str, modality: str) -> np.random.Generator:
    # zlib.crc32 is stable across processes (unlike hash()), so data is reproducible.
    return np.random.default_rng([seed, zlib.crc32(hospital_id.encode()), zlib.crc32(modality.encode())])


def _simulate(hospital: SimulatedHospital, modality: str, n: int, rng: np.random.Generator):
    if modality == "ehr":
        return simulate_ehr(n, rng, hospital.ehr)
    if modality == "ecg":
        return simulate_ecg(n, rng, hospital.ecg)
    return simulate_xray(n, rng, hospital.xray)


def generate_hospital_data(
    data_root: Path,
    hospital: SimulatedHospital,
    seed: int = 2024,
    modalities: Iterable[str] = MODALITIES,
    scale: float = 1.0,
    overwrite: bool = False,
) -> Dict[str, dict]:
    """Write one hospital's simulated partitions under ``data_root/<hospital_id>``."""
    hospital_dir = Path(data_root) / hospital.hospital_id
    manifests = {}
    for modality in modalities:
        existing = read_manifest(hospital_dir, modality)
        if existing is not None and not overwrite:
            manifests[modality] = existing
            continue
        total = max(16, int(round(hospital.sizes[modality] * scale)))
        X, y = _simulate(hospital, modality, total, _rng(seed, hospital.hospital_id, modality))
        n_val = max(4, int(round(total * VAL_FRACTION)))
        manifests[modality] = save_local_dataset(
            hospital_dir,
            modality,
            train=(X[n_val:], y[n_val:]),
            val=(X[:n_val], y[:n_val]),
            source="simulated",
            description=_DESCRIPTIONS[modality],
        )
    return manifests


def generate_all_hospitals(data_root: Path, seed: int = 2024, scale: float = 1.0, overwrite: bool = False):
    return {
        hospital.hospital_id: generate_hospital_data(data_root, hospital, seed, scale=scale, overwrite=overwrite)
        for hospital in SIMULATED_HOSPITALS
    }


def generate_reference_cases(modality: str, seed: int = 7) -> dict:
    """A small *public, synthetic* case set held by the coordinator.

    It is used only to demonstrate individual-prediction explanations. It is
    generated separately from every hospital partition and is never used for
    training or for evaluating the global model.
    """
    rng = np.random.default_rng([seed, zlib.crc32(modality.encode())])
    if modality == "ehr":
        X, y = simulate_ehr(160, rng, EHRProfile())
        cases = list(np.where(y == 1)[0][:3]) + list(np.where(y == 0)[0][:3])
        rest = [i for i in range(len(y)) if i not in set(cases)]
        return {"X": X[cases], "y": y[cases], "background": X[rest][:64]}
    if modality == "ecg":
        X, y = simulate_ecg(120, rng, ECGProfile(class_mix=(0.25, 0.25, 0.25, 0.25)))
        cases = [int(np.where(y == label)[0][0]) for label in range(4)]
        return {"X": X[cases], "y": y[cases], "background": X[:0]}
    X, y = simulate_xray(40, rng, XrayProfile(prevalence=0.5))
    cases = list(np.where(y == 1)[0][:2]) + list(np.where(y == 0)[0][:2])
    return {"X": X[cases], "y": y[cases], "background": X[:0]}
