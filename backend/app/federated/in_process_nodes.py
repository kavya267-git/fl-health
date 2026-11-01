"""Runs the four hospital nodes inside the API process (HOSPITAL_NODES=in-process).

Each node is a ``HospitalNode`` with its own data directory. The nodes reach
the coordinator through ``LocalTransport``, which calls exactly the same
coordinator methods that the HTTP endpoints call for external nodes - so the
data that crosses the boundary is identical in both setups: weights, counts
and summary metrics.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, Optional

from app.federated import coordinator as rounds
from app.federated.coordinator import Coordinator
from app.services.hospital_service import HospitalService
from app.utils.errors import ServiceError
from ml.training.hospital_node import HospitalNode

logger = logging.getLogger("fl.nodes")


class LocalTransport:
    def __init__(self, coordinator: Coordinator, delay_seconds: float = 0.0):
        self.coordinator = coordinator
        #: Optional pause before an update or evaluation is delivered (demo pacing).
        self.delay_seconds = delay_seconds

    def _pause(self) -> None:
        if self.delay_seconds > 0:
            time.sleep(self.delay_seconds)

    def join_round(self, round_id: str, hospital_id: str, data_summary: dict) -> dict:
        return self.coordinator.join(round_id, hospital_id, data_summary)

    def fetch_global_model(self, round_id: str, hospital_id: str, which: str) -> bytes:
        return self.coordinator.global_model_bytes(round_id, hospital_id, which)

    def submit_update(
        self,
        round_id: str,
        hospital_id: str,
        payload: bytes,
        num_samples: int,
        metrics: dict,
        dp_report: dict,
        architecture_signature: str,
    ) -> dict:
        self._pause()
        return self.coordinator.receive_update(
            round_id, hospital_id, payload, num_samples, metrics, dp_report, architecture_signature
        )

    def submit_evaluation(self, round_id: str, hospital_id: str, evaluation: dict, explanation: Optional[dict]) -> dict:
        self._pause()
        return self.coordinator.receive_evaluation(round_id, hospital_id, evaluation, explanation)

    def report_failure(self, round_id: str, hospital_id: str, stage: str, message: str) -> None:
        self.coordinator.report_failure(round_id, hospital_id, stage, message)


class InProcessNodes:
    def __init__(
        self, coordinator: Coordinator, hospitals: HospitalService, data_root: Path, step_delay_seconds: float = 0.0
    ):
        self.coordinator = coordinator
        self.hospitals = hospitals
        self.data_root = Path(data_root)
        self.step_delay_seconds = step_delay_seconds
        self.transport = LocalTransport(coordinator, step_delay_seconds)
        # One worker: local training is CPU-heavy, so rounds run one at a time.
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hospital-nodes")

    def node(self, hospital_id: str) -> HospitalNode:
        return HospitalNode(hospital_id, self.data_root / hospital_id, self.transport)

    def submit(self, round_id: str):
        """Run the round in the background and return immediately."""
        return self._executor.submit(self.run_round, round_id)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def run_round(self, round_id: str) -> None:
        coordinator = self.coordinator
        try:
            infos: Dict[str, dict] = {}
            nodes: Dict[str, HospitalNode] = {}
            for participant in coordinator.participants(round_id):
                hospital_id = participant["hospital_id"]
                if not self.hospitals.get_raw(hospital_id)["online"]:
                    coordinator.report_failure(round_id, hospital_id, "join", "Hospital node is offline.")
                    continue
                nodes[hospital_id] = self.node(hospital_id)
                try:
                    infos[hospital_id] = nodes[hospital_id].join(round_id)
                except Exception as exc:
                    self._report(round_id, hospital_id, "join", exc)

            for hospital_id, info in infos.items():
                if coordinator.get_round(round_id)["status"] in rounds.TERMINAL:
                    return
                try:
                    nodes[hospital_id].train_and_submit(round_id, info)
                except ServiceError as exc:
                    # The coordinator already recorded a rejected update; anything
                    # else (e.g. the round moved on) is reported as a node failure.
                    logger.warning("Round %s: %s update not accepted: %s", round_id, hospital_id, exc.message)
                    self._report(round_id, hospital_id, "training", exc)
                except Exception as exc:
                    logger.exception("Round %s: local training failed at %s", round_id, hospital_id)
                    self._report(round_id, hospital_id, "training", exc)

            if coordinator.get_round(round_id)["status"] != rounds.EVALUATING:
                return
            for participant in coordinator.participants(round_id):
                if participant["status"] != rounds.P_SUBMITTED:
                    continue
                hospital_id = participant["hospital_id"]
                try:
                    nodes[hospital_id].evaluate_and_report(round_id, infos[hospital_id])
                except Exception as exc:
                    logger.exception("Round %s: evaluation failed at %s", round_id, hospital_id)
                    self._report(round_id, hospital_id, "evaluation", exc)
        except Exception as exc:  # never leave a round hanging
            logger.exception("Round %s aborted", round_id)
            coordinator.fail_round(round_id, f"Unexpected error while running the round: {exc}")

    def _report(self, round_id: str, hospital_id: str, stage: str, exc: Exception) -> None:
        message = exc.message if isinstance(exc, ServiceError) else str(exc)
        try:
            self.coordinator.report_failure(round_id, hospital_id, stage, message)
        except Exception:
            logger.exception("Could not record failure for %s in round %s", hospital_id, round_id)
