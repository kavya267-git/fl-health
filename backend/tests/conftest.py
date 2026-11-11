"""Shared fixtures for the backend tests.

Tests run against a temporary SQLite database and temporary storage, with the
NumPy reference models so a full federated round takes well under a second.
"""

from __future__ import annotations

import os

os.environ.setdefault("ML_BACKEND", "numpy-reference")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services.context import bootstrap, build_context  # noqa: E402
from backend_test_helpers import DEMO_PASSWORD, login  # noqa: E402


#: Run the suite against PostgreSQL instead of SQLite: TEST_DATABASE_URL=postgresql://... (a throwaway database:
#: every test starts by emptying its public schema).
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "").strip()


def _fresh_database_url(tmp_path) -> str:
    if not TEST_DATABASE_URL:
        return f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    import psycopg

    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as connection:
        connection.execute("DROP SCHEMA IF EXISTS public CASCADE")
        connection.execute("CREATE SCHEMA public")
    return TEST_DATABASE_URL


@pytest.fixture()
def settings(tmp_path) -> Settings:
    return Settings(
        demo_mode=True,
        hospital_nodes="in-process",
        seed=7,
        simulation_scale=0.2,
        auth_provider="demo",
        demo_jwt_secret="test-jwt-secret-with-enough-length-0123456789",
        demo_password=DEMO_PASSWORD,
        node_token_secret="test-node-secret",
        database_url=_fresh_database_url(tmp_path),
        model_storage_path=tmp_path / "models",
        hospital_data_root=tmp_path / "hospitals",
    )


@pytest.fixture()
def ctx(settings):
    """Service context without the HTTP layer."""
    context = build_context(settings)
    bootstrap(context)
    yield context
    context.close()


@pytest.fixture()
def client(settings):
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture()
def admin(client) -> dict:
    return login(client, "admin@fl-healthcare.demo")


@pytest.fixture()
def coordinator(client) -> dict:
    return login(client, "coordinator@fl-healthcare.demo")


@pytest.fixture()
def viewer(client) -> dict:
    return login(client, "viewer@fl-healthcare.demo")
