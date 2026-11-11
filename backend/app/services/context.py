"""Builds and bootstraps the application's services.

``build_context`` wires the services together; ``bootstrap`` prepares state
(schema, hospitals, models, analytics data). Routers reach services through
the context stored on ``app.state``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.analytics.alert_service import AlertService
from app.analytics.ensemble_service import EnsembleService
from app.analytics.explainability_service import ExplainabilityService
from app.analytics.forecast_service import ForecastService
from app.analytics.planning_service import PlanningService
from app.analytics.situation_service import SituationService
from app.analytics.surveillance_service import SurveillanceService
from app.config import Settings
from app.database import Database
from app.federated.coordinator import Coordinator
from app.federated.deadlines import DeadlineWatcher
from app.federated.in_process_nodes import InProcessNodes
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService
from app.services.hospital_service import HospitalService
from app.services.model_registry import ModelRegistry
from app.services.privacy_service import PrivacyService
from app.services.registration_service import RegistrationService
from app.utils.errors import UnavailableError
from ml.common.datasets import local_data_summary
from ml.common.types import MODALITIES
from ml.registry import TARGET_ARCHITECTURES, configured_backend, get_adapter, torch_available
from ml.simulation.hospitals import SIMULATED_HOSPITALS, generate_hospital_data

logger = logging.getLogger("fl.bootstrap")


@dataclass
class AppContext:
    settings: Settings
    db: Database
    audit: AuditService
    auth: AuthService
    hospitals: HospitalService
    registry: ModelRegistry
    coordinator: Coordinator
    surveillance: SurveillanceService
    forecasts: ForecastService
    explainability: ExplainabilityService
    privacy: PrivacyService
    nodes: Optional[InProcessNodes]
    ensemble: Optional[EnsembleService] = None
    alerts: Optional[AlertService] = None
    situation: Optional[SituationService] = None
    planning: Optional[PlanningService] = None
    deadlines: Optional[DeadlineWatcher] = None
    registrations: Optional[RegistrationService] = None

    def model_backends(self) -> Dict[str, Any]:
        """Which implementation each modality is using right now."""
        backends = {}
        for modality in MODALITIES:
            try:
                adapter = get_adapter(modality)
                backends[modality] = {
                    "architecture": adapter.architecture,
                    "backend": adapter.backend,
                    "target_architecture": TARGET_ARCHITECTURES[modality],
                    "is_target_architecture": adapter.architecture == TARGET_ARCHITECTURES[modality],
                    # Tensor names and shapes: an external node checks its own against this.
                    "architecture_signature": adapter.signature(),
                }
            except Exception as exc:  # e.g. ML_BACKEND=pytorch without torch installed
                backends[modality] = {
                    "architecture": None,
                    "backend": None,
                    "target_architecture": TARGET_ARCHITECTURES[modality],
                    "is_target_architecture": False,
                    "error": str(exc),
                }
        return backends

    def system_config(self) -> Dict[str, Any]:
        settings = self.settings
        return {
            "app_name": settings.app_name,
            "version": settings.app_version,
            "demo_mode": settings.demo_mode,
            "simulated_label": settings.simulated_label,
            "auth_provider": settings.auth_provider,
            "demo_accounts": self.auth.demo_accounts() if settings.auth_provider == "demo" else [],
            # The sign-in page names the demo password only while the server still uses the published default.
            "demo_login_is_default": settings.auth_provider == "demo" and settings.demo_password == "demo-password",
            "signup_enabled": settings.allow_signup,
            "hospital_registration_enabled": settings.allow_hospital_registration and settings.auth_provider == "demo",
            "hospital_nodes": settings.hospital_nodes,
            "ml_backend": configured_backend(),
            "database": "sqlite" if settings.is_sqlite else "postgresql",
            "pytorch_available": torch_available(),
            "model_backends": self.model_backends(),
            "modalities": list(MODALITIES),
        }

    def close(self) -> None:
        if self.ensemble is not None:
            self.ensemble.stop()
        if self.deadlines is not None:
            self.deadlines.stop()
        if self.nodes is not None:
            self.nodes.shutdown()
        self.db.close()


def build_context(settings: Settings) -> AppContext:
    db = Database(settings.database_url)
    db.create_schema()
    audit = AuditService(db)
    auth = AuthService(db, audit, settings)
    hospitals = HospitalService(db, audit, settings.node_token_secret, settings.hospital_nodes)
    registry = ModelRegistry(
        db, settings.model_storage_path, settings.model_keep_versions, settings.seed, settings.model_weights_in_database
    )
    coordinator = Coordinator(
        db, registry, audit, settings.model_storage_path, settings.max_update_bytes, settings.seed
    )
    surveillance = SurveillanceService(db, audit, settings)
    forecasts = ForecastService(db, audit, surveillance)
    explainability = ExplainabilityService(db, registry, audit, settings.model_storage_path)
    privacy = PrivacyService(db, settings)
    nodes = (
        InProcessNodes(coordinator, hospitals, settings.hospital_data_root, settings.demo_step_delay_seconds)
        if settings.hospital_nodes == "in-process"
        else None
    )
    ensemble = EnsembleService(db, surveillance)
    return AppContext(
        settings,
        db,
        audit,
        auth,
        hospitals,
        registry,
        coordinator,
        surveillance,
        forecasts,
        explainability,
        privacy,
        nodes,
        ensemble=ensemble,
        alerts=AlertService(db, audit, surveillance),
        situation=SituationService(db, audit, surveillance, ensemble, settings.app_version),
        planning=PlanningService(
            db, audit, surveillance, ensemble, settings.demo_hospital_regions if settings.demo_mode else None
        ),
        registrations=RegistrationService(db, audit, auth, hospitals),
    )


def bootstrap(ctx: AppContext) -> None:
    """Prepare everything the API needs. Safe to call on every start."""
    settings = ctx.settings
    if settings.auth_provider == "demo":
        ctx.auth.seed_demo_users()

    # Hospitals. With in-process nodes this process also plays the hospitals,
    # so it prepares their simulated data and reads their manifests (counts
    # only). With external nodes, summaries arrive when a node joins a round.
    for hospital in SIMULATED_HOSPITALS:
        hospital_dir = settings.hospital_data_root / hospital.hospital_id
        if settings.hospital_nodes == "in-process":
            if settings.demo_mode:
                generate_hospital_data(
                    settings.hospital_data_root, hospital, seed=settings.seed, scale=settings.simulation_scale
                )
            summary = local_data_summary(hospital_dir)
            modalities = sorted(summary) if summary else []
            simulated = all(entry["simulated"] for entry in summary.values()) if summary else settings.demo_mode
        else:
            existing = ctx.db.fetch_one(
                "SELECT data_summary, modalities FROM hospitals WHERE id = :id", {"id": hospital.hospital_id}
            )
            summary = (existing or {}).get("data_summary") or {}
            modalities = (existing or {}).get("modalities") or list(MODALITIES)
            simulated = settings.demo_mode
        name = hospital.name if settings.demo_mode else f"Hospital {hospital.hospital_id[-1].upper()}"
        ctx.hospitals.upsert(
            hospital.hospital_id, name, hospital.kind if settings.demo_mode else "", modalities, summary, simulated
        )
        if settings.demo_mode and hospital.hospital_id in settings.demo_hospital_regions:
            ctx.db.update(
                "hospitals", {"region_id": settings.demo_hospital_regions[hospital.hospital_id]}, {"id": hospital.hospital_id}
            )

    # In-process nodes cannot resume a round that a previous process left unfinished.
    if settings.hospital_nodes == "in-process":
        recovered = ctx.coordinator.recover_interrupted("The coordinator restarted while this round was running.")
        if recovered:
            logger.warning("Marked %d interrupted round(s) as failed", recovered)

    for modality in MODALITIES:
        try:
            ctx.registry.ensure_initial(modality, is_simulated=settings.demo_mode)
        except UnavailableError as exc:
            logger.error("Model for %s is unavailable: %s", modality, exc.message)

    ctx.explainability.bootstrap()
    ctx.surveillance.bootstrap([h.hospital_id for h in SIMULATED_HOSPITALS])
    ctx.alerts.sync()
    ctx.planning.seed_assumptions()
