"""Helpers shared by the backend tests."""

from __future__ import annotations

import time

DEMO_PASSWORD = "test-password"


def login(client, email: str) -> dict:
    response = client.post("/api/auth/demo-login", json={"email": email, "password": DEMO_PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def wait_for_round(client, headers: dict, round_id: str, timeout: float = 60.0) -> dict:
    """Poll a round until it completes or fails."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/federated/rounds/{round_id}", headers=headers).json()
        if body["status"] in ("COMPLETED", "FAILED"):
            return body
        time.sleep(0.05)
    raise AssertionError(f"Round {round_id} did not finish within {timeout}s")


def run_round(ctx, modality: str = "ehr", **kwargs) -> dict:
    """Run one round synchronously at the service level."""
    created = ctx.coordinator.start_round(modality, ctx.hospitals.list_raw(), "tester", **kwargs)
    ctx.nodes.run_round(created["id"])
    return ctx.coordinator.get_round(created["id"])
