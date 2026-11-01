"""Prediction task for each modality.

Each modality has its own task, label space and metric averaging. Metrics from
different modalities are never comparable with each other.
"""

from __future__ import annotations

from ml.common.types import TaskSpec
from ml.evaluation.metrics import METRIC_DEFINITIONS_BINARY, METRIC_DEFINITIONS_MULTICLASS

EHR_TASK = TaskSpec(
    modality="ehr",
    name="Adverse in-hospital outcome",
    description=(
        "Binary classification from structured admission data: will the admission end in an adverse outcome (yes / no)."
    ),
    task_type="binary",
    class_names=("No adverse outcome", "Adverse outcome"),
    primary_metric="f1",
    metric_definitions=METRIC_DEFINITIONS_BINARY,
)

ECG_TASK = TaskSpec(
    modality="ecg",
    name="Heartbeat classification",
    description=(
        "Four-class classification of single heartbeats using the AAMI grouping: "
        "normal (N), supraventricular ectopic (S), ventricular ectopic (V) and fusion (F)."
    ),
    task_type="multiclass",
    class_names=("N - Normal", "S - Supraventricular ectopic", "V - Ventricular ectopic", "F - Fusion"),
    primary_metric="f1",
    metric_definitions=METRIC_DEFINITIONS_MULTICLASS,
)

XRAY_TASK = TaskSpec(
    modality="xray",
    name="Chest X-ray finding detection",
    description="Binary classification of a frontal chest image: finding present or no finding.",
    task_type="binary",
    class_names=("No finding", "Finding present"),
    primary_metric="f1",
    metric_definitions=METRIC_DEFINITIONS_BINARY,
)

TASKS = {"ehr": EHR_TASK, "ecg": ECG_TASK, "xray": XRAY_TASK}


def get_task(modality: str) -> TaskSpec:
    try:
        return TASKS[modality]
    except KeyError as exc:
        raise ValueError(f"Unknown modality '{modality}'. Expected one of {sorted(TASKS)}") from exc
