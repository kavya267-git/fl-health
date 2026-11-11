"""What a newly approved hospital needs to connect: the data template and the connection status.

The template is a small zip with column lists, one example row of **made-up values**, and how to arrange
the folder that ``setup_hospital.py --data`` reads. It contains no real data.
"""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any, Dict

from ml.common.data_check import EHR_BOUNDS, LABEL_NAMES, MAX_MISSING_SHARE, MIN_TRAIN_RECORDS
from ml.ecg.preprocess import ECG_BEAT_LENGTH
from ml.ehr.features import EHR_FEATURES, EHR_LABEL_COLUMN

#: One made-up EHR row (not a real patient), inside every bound of the local data check.
EXAMPLE_EHR_ROW = {
    "age": 64, "sex_male": 1, "heart_rate": 92, "systolic_bp": 128, "resp_rate": 19, "temperature_c": 37.4,
    "spo2": 95, "wbc": 10.2, "creatinine": 1.1, "lactate": 1.8, "glucose": 142, "hemoglobin": 12.9,
    "prior_admissions_12m": 1, "comorbidity_index": 3,
}


def _readme(hospital_id: str) -> str:
    ehr_lines = "\n".join(
        f"  {f.name:22s} {f.unit:12s} {EHR_BOUNDS[f.name][0]}-{EHR_BOUNDS[f.name][1]:<6}  {f.description}"
        for f in EHR_FEATURES
    )
    return f"""MediFed data template for {hospital_id}
=========================================

Everything in this zip is an EXAMPLE with made-up values. It contains no patient data.
Your data stays on your machine: the node trains on it locally and sends only model
weights, record counts and summary metrics. Nothing is uploaded from your folder.

1. EHR (one row per admission)
------------------------------
Columns (name, unit, accepted range, meaning), then `{EHR_LABEL_COLUMN}`:
{ehr_lines}
  {EHR_LABEL_COLUMN:22s} 0 or 1       {LABEL_NAMES['ehr'][0]} (0) / {LABEL_NAMES['ehr'][1]} (1)

Empty cells are allowed (at most {MAX_MISSING_SHARE:.0%} per column); your node fills them by nearest-neighbour
imputation fitted on your own training records. See ehr_example.csv for one made-up row.

2. ECG (one row per heartbeat)
------------------------------
{ECG_BEAT_LENGTH} samples of one beat at 125 Hz (lead MLII, scaled to 0-1), then the class:
0 = N (normal), 1 = S (supraventricular ectopic), 2 = V (ventricular ectopic), 3 = F (fusion).
No header row. This is the MIT-BIH "heartbeat" CSV format. See ecg_example.csv.

3. Chest X-ray
--------------
Frontal images as 8-bit greyscale, with a label per image: 0 = no finding, 1 = finding.
Prepare them with scripts/prepare_real_data.py xray (NIH ChestX-ray14 index format).

Turning your CSV files into the folder the node reads
-----------------------------------------------------
From the repository folder, once per kind of data:

  python scripts/prepare_real_data.py --hospitals {hospital_id} --data-root my-data ehr --csv admissions.csv
  python scripts/prepare_real_data.py --hospitals {hospital_id} --data-root my-data ecg --csv beats.csv

This writes my-data/{hospital_id}/ehr/ and .../ecg/ (training and held-out splits). Then start the node with

  python scripts/setup_hospital.py {hospital_id} --server <server> --token <token> --data my-data/{hospital_id}

The node checks the folder first (columns, types, ranges, counts, labels; at least {MIN_TRAIN_RECORDS}
training records per kind of data) and prints pass or fail for each. Only that result and the counts
are reported to the server. You are invited to rounds only for the kinds of data you declared and
whose check passed.
"""


def data_template_zip(hospital_id: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("README.txt", _readme(hospital_id))
        names = [f.name for f in EHR_FEATURES] + [EHR_LABEL_COLUMN]
        row = [str(EXAMPLE_EHR_ROW[f.name]) for f in EHR_FEATURES] + ["0"]
        archive.writestr("ehr_example.csv", ",".join(names) + "\n" + ",".join(row) + "\n")
        # A smooth made-up curve, not a recording.
        beat = [round(0.5 + 0.4 * (1 if i == 40 else 0) + 0.05 * ((i % 20) / 20), 3) for i in range(ECG_BEAT_LENGTH)]
        archive.writestr("ecg_example.csv", ",".join(str(v) for v in beat) + ",0\n")
        archive.writestr(
            "columns.json",
            json.dumps(
                {
                    "ehr": {"columns": names, "bounds": {k: list(v) for k, v in EHR_BOUNDS.items()}},
                    "ecg": {"samples_per_beat": ECG_BEAT_LENGTH, "sampling_rate_hz": 125, "labels": LABEL_NAMES["ecg"]},
                    "xray": {"format": "8-bit greyscale, [n, height, width]", "labels": LABEL_NAMES["xray"]},
                },
                indent=2,
            ),
        )
    return buffer.getvalue()


def connection_status(ctx: Any, hospital_id: str) -> Dict[str, Any]:
    """The 'Connect your hospital' panel: token, node, data check, invitations. Counts and timestamps only."""
    raw = ctx.hospitals.get_raw(hospital_id)
    registered = raw["kind"] == "registered"
    node = raw.get("node")
    check = raw.get("data_check") or {}
    declared = (raw.get("declared_modalities") or []) if registered else list(raw.get("modalities") or [])
    if node is None or not node.get("connected"):
        step = "NOT_CONNECTED"
    elif registered and not any(c.get("passed") for c in check.values()):
        step = "CONNECTED"
    elif raw.get("modalities"):
        step = "INVITED"
    else:
        step = "DATA_CHECKED"
    return {
        "registered": registered,
        "step": step,
        "token": ctx.hospitals.token_status(hospital_id) if registered else None,
        "node": node,
        "declared_modalities": declared,
        "data_check": check,
        "invited_modalities": raw.get("modalities") or [],
        "region_id": raw.get("region_id"),
        "node_mode": "external" if ctx.hospitals.external_nodes else "in-process",
        "server_url": ctx.settings.public_api_url or ctx.settings.api_base_url,
    }
