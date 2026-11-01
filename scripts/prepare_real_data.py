#!/usr/bin/env python3
"""Split real datasets into the four hospital partitions.

Examples
--------
EHR (a tabular extract with the 14 features in ml/ehr/features.py and a label)::

    python scripts/prepare_real_data.py ehr --csv admissions.csv --group-column subject_id \\
        --mapping '{"anchor_age": "age", "hospital_expire_flag": "label"}'

ECG (MIT-BIH heartbeat CSV export)::

    python scripts/prepare_real_data.py ecg --csv mitbih_train.csv mitbih_test.csv

X-ray (NIH ChestX-ray14)::

    python scripts/prepare_real_data.py xray --entries Data_Entry_2017.csv --images images/ --size 224

Then start the API with DEMO_MODE=false (see docs/setup.md).
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ml.common.real_data import (  # noqa: E402
    DEFAULT_HOSPITALS,
    prepare_chestxray14,
    prepare_ecg_heartbeat_csv,
    prepare_ehr_csv,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-root", type=Path, default=ROOT / "data" / "hospitals")
    parser.add_argument("--hospitals", nargs="+", default=list(DEFAULT_HOSPITALS))
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--alpha",
        type=float,
        default=1.0,
        help="Dirichlet concentration for label skew between hospitals; use 0 for an even split.",
    )
    sub = parser.add_subparsers(dest="modality", required=True)

    ehr = sub.add_parser("ehr")
    ehr.add_argument("--csv", type=Path, required=True)
    ehr.add_argument("--mapping", type=json.loads, default=None, help="JSON object: your column -> feature name")
    ehr.add_argument("--label-column", default="label")
    ehr.add_argument(
        "--group-column", default=None, help="Patient identifier column, to keep a patient in one hospital"
    )
    ehr.add_argument("--source", default="mimic-iv")

    ecg = sub.add_parser("ecg")
    ecg.add_argument("--csv", type=Path, nargs="+", required=True)
    ecg.add_argument("--source", default="mit-bih")

    xray = sub.add_parser("xray")
    xray.add_argument("--entries", type=Path, required=True, help="Data_Entry_2017.csv")
    xray.add_argument("--images", type=Path, required=True)
    xray.add_argument("--size", type=int, default=224)
    xray.add_argument("--limit", type=int, default=None)
    xray.add_argument("--source", default="nih-chestxray14")

    args = parser.parse_args()
    common = dict(
        data_root=args.data_root,
        hospital_ids=args.hospitals,
        seed=args.seed,
        alpha=None if args.alpha == 0 else args.alpha,
    )
    if args.modality == "ehr":
        manifests = prepare_ehr_csv(
            args.csv,
            column_mapping=args.mapping,
            label_column=args.label_column,
            group_column=args.group_column,
            source=args.source,
            **common,
        )
    elif args.modality == "ecg":
        manifests = prepare_ecg_heartbeat_csv(args.csv, source=args.source, **common)
    else:
        manifests = prepare_chestxray14(
            args.entries, args.images, image_size=args.size, limit=args.limit, source=args.source, **common
        )
    for hospital_id, manifest in manifests.items():
        print(
            f"{hospital_id}: {manifest['splits']['train']} train / {manifest['splits']['val']} validation ({manifest['source']})"
        )
    print(f"Written under {args.data_root}")


if __name__ == "__main__":
    main()
