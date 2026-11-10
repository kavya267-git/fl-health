"""Compute and store the ensemble forecast for every region and disease, before a demo.

    python scripts/precompute_forecasts.py

Uses the same settings as the API (backend/.env) and the same database, so the running API reads the stored
run at once and nothing waits on training. If a run for the current data is already stored, it does nothing.
Takes several minutes on a laptop CPU (the LSTM and Prophet are refitted at every validation origin).
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT)]

from app.config import load_settings  # noqa: E402
from app.services.context import bootstrap, build_context  # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    for name in ("cmdstanpy", "prophet"):
        logging.getLogger(name).setLevel(logging.ERROR)
    ctx = build_context(load_settings())
    try:
        bootstrap(ctx)
        if not ctx.ensemble.needs_run():
            latest = ctx.ensemble.latest()
            print(f"Already stored: run {latest['run_id']}, data through {latest['data_through']}. Nothing to do.")
            return 0
        started = time.time()
        latest = ctx.ensemble.run()
        if latest is None:
            print("The ensemble forecast failed; see the log above.")
            return 1
        print(
            f"Stored run {latest['run_id']}: {len(latest['forecasts'])} series forecast, "
            f"{len(latest['excluded'])} without a forecast, data through {latest['data_through']}, "
            f"{time.time() - started:.0f} s."
        )
        return 0
    finally:
        ctx.close()


if __name__ == "__main__":
    sys.exit(main())
