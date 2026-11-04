"""The ensemble forecast for every region and disease, computed off the request path and stored.

A run trains the global LSTM and refits ARIMA and Prophet many times (several minutes on a laptop CPU), so
requests never start one. Instead:

* ``start_background()`` (called after bootstrap) runs it on a background thread when the stored run does not
  match the current data, and checks again every ``check_seconds`` so new weeks start a new run;
* every finished run is stored in ``ensemble_runs`` with the data version it was computed from, so a restart
  with unchanged data reuses it without retraining;
* ``scripts/precompute_forecasts.py`` runs it in the foreground before a demo.

Requests call ``latest()``: the newest finished run for the current data, or None while it is being computed.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional

from analytics.forecasting.live_ensemble import LiveEnsembleConfig, run_live_ensemble
from app.analytics.surveillance_service import SurveillanceService
from app.database import Database
from app.utils.time import utc_now_iso

logger = logging.getLogger("fl.ensemble")


class EnsembleService:
    def __init__(self, db: Database, surveillance: SurveillanceService, config: LiveEnsembleConfig = LiveEnsembleConfig()):
        self.db = db
        self.surveillance = surveillance
        self.config = config
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.progress: Optional[str] = None

    # ---------------------------------------------------------------- reading
    def latest(self) -> Optional[Dict[str, Any]]:
        """The newest finished run computed from the current data, or None."""
        try:
            version = self.surveillance._data_version()
        except Exception:  # noqa: BLE001 - no surveillance data, so no forecast
            return None
        row = self.db.fetch_one(
            "SELECT * FROM ensemble_runs WHERE data_version = :v AND status = 'DONE' ORDER BY id DESC LIMIT 1",
            {"v": version},
        )
        return None if row is None else {**row["payload"], "run_id": row["id"], "computed_at": row["finished_at"]}

    def status(self) -> Dict[str, Any]:
        latest = self.latest()
        failed = self.db.fetch_one("SELECT error, finished_at FROM ensemble_runs WHERE status = 'FAILED' ORDER BY id DESC LIMIT 1")
        return {
            "ready": latest is not None,
            "running": self.running(),
            "progress": self.progress if self.running() else None,
            "last_error": failed["error"] if failed and latest is None else None,
        }

    def running(self) -> bool:
        return self._lock.locked()

    def forecast_for(self, disease: str, region_id: str) -> Optional[list]:
        latest = self.latest()
        return None if latest is None else latest["forecasts"].get(f"{disease}:{region_id}")

    # ---------------------------------------------------------------- computing
    def needs_run(self) -> bool:
        return self.latest() is None

    def run(self) -> Optional[Dict[str, Any]]:
        """Compute and store a run for the current data (blocking). Returns None if one is already running."""
        if not self._lock.acquire(blocking=False):
            return None
        run_id = None
        try:
            version = self.surveillance._data_version()
            started = utc_now_iso()
            run_id = self.db.insert(
                "ensemble_runs",
                {"data_version": version, "status": "RUNNING", "started_at": started, "is_simulated": self.surveillance.is_simulated()},
            )["id"]
            series, weeks = {}, None
            for disease in self.surveillance.diseases():
                regional = self.surveillance.regional_series(disease["id"])
                weeks = regional["weeks"]
                for region_id, values in regional["counts"].items():
                    series[f"{disease['id']}:{region_id}"] = values

            def progress(message: str) -> None:
                self.progress = message
                logger.info("Ensemble forecast: %s", message)

            payload = run_live_ensemble(series, weeks, self.config, progress)
            self.db.update(
                "ensemble_runs", {"status": "DONE", "finished_at": utc_now_iso(), "payload": payload}, {"id": run_id}
            )
            logger.info("Ensemble forecast stored (run %s, data through %s)", run_id, payload["data_through"])
            return self.latest()
        except Exception as exc:  # noqa: BLE001 - recorded on the run and shown as "not available"
            logger.exception("Ensemble forecast failed")
            if run_id is not None:
                self.db.update(
                    "ensemble_runs", {"status": "FAILED", "finished_at": utc_now_iso(), "error": str(exc)[:500]}, {"id": run_id}
                )
            return None
        finally:
            self.progress = None
            self._lock.release()

    def start_background(self, check_seconds: float = 600.0) -> None:
        """Run now if needed, then re-check every ``check_seconds`` for new data."""

        def loop() -> None:
            while not self._stop.is_set():
                try:
                    if self.needs_run():
                        self.run()
                except Exception:  # noqa: BLE001 - keep checking; the failure is logged in run()
                    logger.exception("Ensemble background check failed")
                self._stop.wait(check_seconds)

        self._thread = threading.Thread(target=loop, name="ensemble-forecast", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
