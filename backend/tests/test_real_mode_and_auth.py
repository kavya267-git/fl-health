"""Real mode (DEMO_MODE=false) and the Supabase auth provider."""

import numpy as np
import pandas as pd
import pytest

from app.config import Settings, load_settings
from app.services import auth_service
from app.services.auth_service import SupabaseAuthProvider
from app.services.context import bootstrap, build_context
from app.utils.errors import AuthenticationFailed, UnavailableError
from ml.common.real_data import prepare_ehr_csv
from ml.ehr.features import EHR_FEATURE_NAMES
from ml.simulation.ehr import simulate_ehr


class FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


@pytest.fixture()
def real_settings(tmp_path):
    return Settings(
        demo_mode=False,
        hospital_nodes="in-process",
        auth_provider="supabase",
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="service-role-key",
        admin_emails=["lead@hospital.example"],
        node_token_secret="node-secret",
        database_url=f"sqlite:///{(tmp_path / 'real.db').as_posix()}",
        model_storage_path=tmp_path / "models",
        hospital_data_root=tmp_path / "hospitals",
    )


@pytest.fixture()
def real_ctx(real_settings, tmp_path):
    X, y = simulate_ehr(400, np.random.default_rng(0))
    frame = pd.DataFrame(X, columns=EHR_FEATURE_NAMES)
    frame["label"] = y
    frame.to_csv(tmp_path / "extract.csv", index=False)
    prepare_ehr_csv(tmp_path / "extract.csv", real_settings.hospital_data_root, source="site-extract", alpha=None)
    context = build_context(real_settings)
    bootstrap(context)
    yield context
    context.close()


def test_real_mode_uses_prepared_data_and_generates_nothing(real_ctx, real_settings):
    hospitals = real_ctx.hospitals.list()
    assert len(hospitals) == 4
    for hospital in hospitals:
        assert hospital["is_simulated"] is False
        assert hospital["modalities"] == ["ehr"]  # only what was prepared; nothing is simulated to fill gaps
        assert hospital["data_summary"]["ehr"]["source"] == "site-extract"
        assert not (real_settings.hospital_data_root / hospital["id"] / "ecg").exists()
    assert real_ctx.system_config()["demo_accounts"] == []


def test_real_mode_round_is_not_labelled_simulated(real_ctx):
    created = real_ctx.coordinator.start_round("ehr", real_ctx.hospitals.list_raw(), "lead", is_simulated=False)
    real_ctx.nodes.run_round(created["id"])
    finished = real_ctx.coordinator.get_round(created["id"])
    assert finished["status"] == "COMPLETED" and finished["is_simulated"] is False
    model = real_ctx.registry.describe("ehr")
    assert model["is_simulated"] is False and model["dataset"]["sources"] == ["site-extract"]


def test_modality_without_data_cannot_start_a_round(real_ctx):
    from app.utils.errors import ConflictError

    with pytest.raises(ConflictError, match="0 online hospital"):
        real_ctx.coordinator.start_round("xray", real_ctx.hospitals.list_raw(), "lead")


def test_surveillance_is_unavailable_until_configured(real_ctx):
    with pytest.raises(UnavailableError, match="REGIONS_GEOJSON_PATH"):
        real_ctx.surveillance.options()
    with pytest.raises(UnavailableError):
        real_ctx.forecasts.forecast(None, None, 8)


def test_supabase_token_is_verified_and_user_is_provisioned(real_ctx, monkeypatch):
    calls = []

    def fake_get(url, headers, timeout):
        calls.append((url, headers))
        if headers["Authorization"] == "Bearer good-token":
            return FakeResponse(200, {"id": "user-123", "email": "Lead@Hospital.example"})
        if headers["Authorization"] == "Bearer viewer-token":
            return FakeResponse(200, {"id": "user-456", "email": "someone@hospital.example"})
        return FakeResponse(401, {"msg": "invalid JWT"})

    monkeypatch.setattr(auth_service.requests, "get", fake_get)
    admin = real_ctx.auth.authenticate("good-token")
    assert admin["email"] == "lead@hospital.example" and admin["role"] == "admin"  # listed in ADMIN_EMAILS
    assert admin["provider"] == "supabase"
    assert calls[0][0] == "https://example.supabase.co/auth/v1/user"
    assert calls[0][1]["apikey"] == "service-role-key"

    viewer = real_ctx.auth.authenticate("viewer-token")
    assert viewer["role"] == "viewer"  # new users start read-only

    real_ctx.auth.authenticate("good-token")
    assert len(calls) == 2  # the first verification was cached

    with pytest.raises(AuthenticationFailed):
        real_ctx.auth.authenticate("bad-token")
    with pytest.raises(Exception, match="disabled"):
        real_ctx.auth.demo_login("admin@fl-healthcare.demo", "demo-password")


def test_supabase_outage_is_reported_as_unavailable(monkeypatch):
    def boom(*args, **kwargs):
        raise auth_service.requests.ConnectionError("no route")

    monkeypatch.setattr(auth_service.requests, "get", boom)
    with pytest.raises(UnavailableError):
        SupabaseAuthProvider("https://example.supabase.co", "key").verify("token")


def test_settings_refuse_real_mode_without_supabase(monkeypatch):
    for name in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "DATABASE_URL", "AUTH_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DEMO_MODE", "false")
    with pytest.raises(ValueError, match="requires Supabase"):
        load_settings()
    monkeypatch.setenv("DEMO_MODE", "true")
    settings = load_settings()
    assert settings.auth_provider == "demo" and settings.is_sqlite
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "key")
    assert load_settings().auth_provider == "supabase"
