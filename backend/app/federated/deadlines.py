"""Background check that drops hospitals which miss a round's deadline.

A hospital on another machine can crash, lose its network or be switched off
mid-round. Without a deadline the round would wait for it forever; with one,
the coordinator drops it and carries on with the hospitals that did report.
"""

from __future__ import annotations

import logging
import threading

from app.federated.coordinator import Coordinator

logger = logging.getLogger("fl.deadlines")


class DeadlineWatcher:
    def __init__(self, coordinator: Coordinator, interval_seconds: float = 2.0):
        self.coordinator = coordinator
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="round-deadlines", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                for round_id in self.coordinator.enforce_deadlines():
                    logger.info("Round %s: deadline reached, late hospitals dropped", round_id)
            except Exception:
                logger.exception("Deadline check failed")
