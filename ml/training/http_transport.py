"""HTTP transport: lets a hospital node on another machine reach the coordinator API."""

from __future__ import annotations

import json
import time
from typing import Optional

import requests


class CoordinatorError(RuntimeError):
    """The coordinator answered with an error status."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(f"Coordinator returned {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


class HttpTransport:
    def __init__(
        self, base_url: str, node_token: str, timeout: float = 120.0, session: Optional[requests.Session] = None
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()
        self.headers = {"X-Hospital-Token": node_token}

    def _url(self, path: str) -> str:
        return f"{self.base_url}/api/federated{path}"

    @staticmethod
    def _check(response) -> None:
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise CoordinatorError(response.status_code, str(detail))

    def join_round(self, round_id: str, hospital_id: str, data_summary: dict) -> dict:
        response = self.session.post(
            self._url(f"/rounds/{round_id}/participate"),
            json={"hospital_id": hospital_id, "data_summary": data_summary},
            headers=self.headers,
            timeout=self.timeout,
        )
        self._check(response)
        return response.json()

    def fetch_global_model(self, round_id: str, hospital_id: str, which: str) -> bytes:
        response = self.session.get(
            self._url(f"/rounds/{round_id}/global-model"),
            params={"hospital_id": hospital_id, "which": which},
            headers=self.headers,
            timeout=self.timeout,
        )
        self._check(response)
        return response.content

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
        response = self.session.post(
            self._url(f"/rounds/{round_id}/updates"),
            data={
                "hospital_id": hospital_id,
                "num_samples": str(num_samples),
                "metrics": json.dumps(metrics),
                "dp_report": json.dumps(dp_report),
                "architecture_signature": architecture_signature,
            },
            files={"weights": ("update.npz", payload, "application/octet-stream")},
            headers=self.headers,
            timeout=self.timeout,
        )
        self._check(response)
        return response.json()

    def submit_evaluation(self, round_id: str, hospital_id: str, evaluation: dict, explanation: Optional[dict]) -> dict:
        response = self.session.post(
            self._url(f"/rounds/{round_id}/evaluations"),
            json={"hospital_id": hospital_id, "evaluation": evaluation, "explanation": explanation},
            headers=self.headers,
            timeout=self.timeout,
        )
        self._check(response)
        return response.json()

    def report_failure(self, round_id: str, hospital_id: str, stage: str, message: str) -> None:
        try:
            self.session.post(
                self._url(f"/rounds/{round_id}/failures"),
                json={"hospital_id": hospital_id, "stage": stage, "message": message[:500]},
                headers=self.headers,
                timeout=self.timeout,
            )
        except requests.RequestException:
            pass  # reporting a failure must never mask the original error

    def system_config(self) -> dict:
        """The coordinator's public configuration (mode, model backends and signatures)."""
        response = self.session.get(f"{self.base_url}/api/system/config", timeout=self.timeout)
        self._check(response)
        return response.json()

    def heartbeat(self, beat: dict) -> dict:
        """Tell the coordinator this node is up. ``beat`` holds machine facts and record counts only."""
        response = self.session.post(
            self._url("/node/heartbeat"), json=beat, headers=self.headers, timeout=min(self.timeout, 15.0)
        )
        self._check(response)
        return response.json()

    def pending_rounds(self, hospital_id: str) -> list:
        """Ids of open rounds this hospital has been invited to and not yet joined."""
        response = self.session.get(
            self._url("/node/rounds"), params={"hospital_id": hospital_id}, headers=self.headers, timeout=self.timeout
        )
        self._check(response)
        return response.json()["round_ids"]

    def wait_for_status(
        self, round_id: str, hospital_id: str, statuses, poll_seconds: float = 2.0, max_wait: float = 3600.0
    ) -> dict:
        """Poll the round until it reaches one of ``statuses`` (or fails)."""
        deadline = time.monotonic() + max_wait
        while time.monotonic() < deadline:
            response = self.session.get(
                self._url(f"/rounds/{round_id}/node-status"),
                params={"hospital_id": hospital_id},
                headers=self.headers,
                timeout=self.timeout,
            )
            self._check(response)
            payload = response.json()
            if payload["status"] in statuses or payload["status"] == "FAILED":
                return payload
            time.sleep(poll_seconds)
        raise TimeoutError(f"Round {round_id} did not reach {statuses} within {max_wait:.0f}s")
