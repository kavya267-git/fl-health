#!/usr/bin/env python3
"""Run a few federated rounds up front so the dashboards have history.

Uses the same settings as the API (backend/.env) and runs with the API stopped.
Every round is real training on the simulated hospital data.

    python scripts/seed_demo.py --rounds 3
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from app.config import load_settings  # noqa: E402
from app.services.context import bootstrap, build_context  # noqa: E402
from ml.common.types import MODALITIES  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rounds", type=int, default=3, help="Rounds per modality")
    parser.add_argument("--modalities", nargs="+", default=list(MODALITIES), choices=list(MODALITIES))
    parser.add_argument("--local-epochs", type=int, default=2)
    args = parser.parse_args()

    settings = load_settings()
    if settings.hospital_nodes != "in-process":
        sys.exit("seed_demo.py needs HOSPITAL_NODES=in-process.")
    ctx = build_context(settings)
    bootstrap(ctx)
    try:
        for modality in args.modalities:
            for _ in range(args.rounds):
                created = ctx.coordinator.start_round(
                    modality,
                    ctx.hospitals.list_raw(),
                    "seed_demo.py",
                    local_epochs=args.local_epochs,
                    is_simulated=settings.demo_mode,
                )
                ctx.nodes.run_round(created["id"])
                done = ctx.coordinator.get_round(created["id"])
                metrics = done["global_metrics"] or {}
                summary = ", ".join(f"{k}={metrics[k]:.3f}" for k in ("accuracy", "f1", "loss") if k in metrics)
                print(f"{done['id']}: {done['status']} {summary or done['error']}")
    finally:
        ctx.close()


if __name__ == "__main__":
    main()
