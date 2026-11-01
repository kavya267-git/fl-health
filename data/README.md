# Data

This directory holds **hospital-side** data at runtime. Nothing in it is committed.

```
data/hospitals/
    hospital_a/
        ehr/   train.csv  val.csv  manifest.json
        ecg/   train.npz  val.npz  manifest.json
        xray/  train.npz  val.npz  manifest.json
    hospital_b/ ...
    hospital_c/ ...
    hospital_d/ ...
```

Each `hospital_*` directory belongs to one hospital node. Only code running as that node reads it
(`ml/training/hospital_node.py`). The coordinator is never given this path: it receives model weights, sample
counts and summary metrics, and stores its own state elsewhere (`ml/checkpoints/` and the database).

## Demo mode

With `DEMO_MODE=true` the server generates simulated partitions here on first start
(`ml/simulation/`). They are synthetic: generated admissions, cartoon ECG beats and geometric chest
phantoms. They contain no patient information and have no clinical meaning. Delete `data/hospitals/` to
regenerate them.

## Real datasets

Real data is never downloaded for you, and none is included. The datasets this project is designed around
have their own access terms:

| Modality | Dataset | Access |
| --- | --- | --- |
| EHR | MIMIC-IV | Credentialed PhysioNet account, CITI training, signed data use agreement |
| ECG | MIT-BIH Arrhythmia Database | Open on PhysioNet (Open Data Commons Attribution licence) |
| X-ray | NIH ChestX-ray14 | Public download from the NIH Clinical Center; cite the dataset paper |

Check the current terms yourself before use. Once you have the files, split them into hospital partitions:

```bash
# EHR: a tabular extract with the 14 features in ml/ehr/features.py plus a binary label
python scripts/prepare_real_data.py ehr --csv admissions.csv --group-column subject_id \
    --mapping '{"anchor_age": "age", "hospital_expire_flag": "label"}'

# ECG: the MIT-BIH "heartbeat" CSV export (187 samples + class per row)
python scripts/prepare_real_data.py ecg --csv mitbih_train.csv mitbih_test.csv

# X-ray: NIH ChestX-ray14 index file and image folder
python scripts/prepare_real_data.py xray --entries Data_Entry_2017.csv --images images/ --size 224
```

The script keeps all of a patient's records in one hospital and on one side of the train/validation split
whenever a patient identifier is available, and writes the same layout as above. Building the EHR extract
from MIMIC-IV's raw tables (choosing the cohort, taking first-recorded vitals and labs, defining the outcome)
is your modelling decision and is not done here.

## Aggregated surveillance data (real mode)

Set `REGIONS_GEOJSON_PATH` to your region boundaries and `SURVEILLANCE_REPORTS_CSV` to a file of
hospital-level weekly totals:

```
hospital_id,region_id,disease,week_start,case_count,suppressed
hospital_a,D01,dengue,2025-03-03,12,false
hospital_b,D01,dengue,2025-03-03,,true
```

`week_start` must be a Monday. Counts from 1 to 4 must be suppressed (left empty, `suppressed=true`) before
the file leaves the hospital; the loader rejects files that contain them.
