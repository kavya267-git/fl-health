"""Application settings, read from environment variables (see backend/.env.example)."""

from __future__ import annotations

import os
import secrets
from datetime import date
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from ml import __version__

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent

load_dotenv(BACKEND_DIR / ".env")

SIMULATED_LABEL = "SIMULATED / DEMONSTRATION DATA"


def _flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _path(name: str, default: Path) -> Path:
    value = os.getenv(name, "").strip()
    return Path(value).expanduser().resolve() if value else default.resolve()


def _optional_path(name: str) -> Optional[Path]:
    value = os.getenv(name, "").strip()
    return Path(value).expanduser().resolve() if value else None


def _optional_monday(name: str) -> Optional[date]:
    """A week start (YYYY-MM-DD, a Monday), or None when unset."""
    value = os.getenv(name, "").strip()
    if not value:
        return None
    day = date.fromisoformat(value)
    if day.weekday() != 0:
        raise ValueError(f"{name} must be a Monday (the start of a week), got {value} ({day:%A})")
    return day


def _list(name: str, default: str = "") -> List[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


class Settings(BaseModel):
    app_name: str = "PrivaFuse"
    app_version: str = __version__

    # Mode ------------------------------------------------------------------
    demo_mode: bool = True
    #: "in-process" runs the four hospital nodes as threads inside the API
    #: process; "external" expects separate node processes that call the API.
    hospital_nodes: str = "in-process"
    seed: int = 2024
    #: Multiplier on the size of the simulated hospital datasets (demo mode).
    simulation_scale: float = 1.0
    #: Pause (seconds) after each in-process hospital step, so a round's
    #: progress can be watched even when training itself takes milliseconds.
    demo_step_delay_seconds: float = 0.0

    # Auth ------------------------------------------------------------------
    auth_provider: str = "demo"  # "supabase" | "demo"
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    admin_emails: List[str] = Field(default_factory=list)
    demo_jwt_secret: str = ""
    demo_password: str = "demo-password"
    node_token_secret: str = ""
    #: Whether visitors may create their own (viewer) account from the sign-in page.
    allow_signup: bool = True

    # Storage ---------------------------------------------------------------
    database_url: str = ""
    model_storage_path: Path = REPO_ROOT / "ml" / "checkpoints"
    hospital_data_root: Path = REPO_ROOT / "data" / "hospitals"
    model_keep_versions: int = 5
    max_update_bytes: int = 256 * 1024 * 1024

    # Analytics -------------------------------------------------------------
    regions_geojson_path: Optional[Path] = None
    region_id_field: str = "region_id"
    region_name_field: str = "name"
    region_population_field: str = "population"
    # Optional populations (region_id, population) for rates per 100,000, e.g. Census 2011 district totals.
    region_populations_csv: Optional[Path] = None
    region_population_source: str = "Census 2011"
    # Background ensemble forecast for every region and disease (off in tests; on by default in the app).
    ensemble_forecasts: bool = False
    surveillance_reports_csv: Optional[Path] = None
    suppression_threshold: int = 5
    surveillance_weeks: int = 104
    # Demo mode only: the last week of the simulated reports. None = the last complete week (rolling, so the
    # data moves on every Monday). Set it for a demo so every rehearsal shows the same hotspots and forecasts.
    simulation_end_week: Optional[date] = None

    # HTTP ------------------------------------------------------------------
    cors_origins: List[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    api_base_url: str = "http://localhost:8000"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def simulated_label(self) -> str:
        return SIMULATED_LABEL


def load_settings() -> Settings:
    demo_mode = _flag("DEMO_MODE", True)
    supabase_url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()

    provider = os.getenv("AUTH_PROVIDER", "auto").strip().lower()
    if provider == "auto":
        provider = "supabase" if supabase_url and service_key else "demo"
    if provider not in ("supabase", "demo"):
        raise ValueError("AUTH_PROVIDER must be 'auto', 'supabase' or 'demo'")
    if provider == "supabase" and not (supabase_url and service_key):
        raise ValueError("AUTH_PROVIDER=supabase requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY")
    if provider == "demo" and not demo_mode:
        raise ValueError(
            "DEMO_MODE=false requires Supabase authentication. Set SUPABASE_URL and "
            "SUPABASE_SERVICE_ROLE_KEY, or set DEMO_MODE=true to use the built-in demo accounts."
        )

    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        if not demo_mode:
            raise ValueError("DEMO_MODE=false requires DATABASE_URL (your Supabase Postgres connection string)")
        database_url = f"sqlite:///{(BACKEND_DIR / 'var' / 'fl_healthcare.db').as_posix()}"

    hospital_nodes = os.getenv("HOSPITAL_NODES", "in-process").strip().lower()
    if hospital_nodes not in ("in-process", "external"):
        raise ValueError("HOSPITAL_NODES must be 'in-process' or 'external'")

    # Secrets that are not configured are generated per process. That is fine
    # for a local demo (sessions simply end when the server restarts).
    demo_secret = os.getenv("DEMO_JWT_SECRET", "").strip() or secrets.token_hex(32)
    node_secret = os.getenv("NODE_TOKEN_SECRET", "").strip() or secrets.token_hex(32)

    return Settings(
        demo_mode=demo_mode,
        hospital_nodes=hospital_nodes,
        seed=int(os.getenv("SEED", "2024")),
        simulation_scale=float(os.getenv("SIMULATION_SCALE", "1.0")),
        demo_step_delay_seconds=max(0.0, float(os.getenv("DEMO_STEP_DELAY_SECONDS", "0"))),
        auth_provider=provider,
        supabase_url=supabase_url,
        supabase_service_role_key=service_key,
        admin_emails=[email.lower() for email in _list("ADMIN_EMAILS")],
        demo_jwt_secret=demo_secret,
        demo_password=os.getenv("DEMO_PASSWORD", "demo-password"),
        node_token_secret=node_secret,
        allow_signup=_flag("ALLOW_SIGNUP", True),
        database_url=database_url,
        model_storage_path=_path("MODEL_STORAGE_PATH", REPO_ROOT / "ml" / "checkpoints"),
        hospital_data_root=_path("HOSPITAL_DATA_ROOT", REPO_ROOT / "data" / "hospitals"),
        model_keep_versions=int(os.getenv("MODEL_KEEP_VERSIONS", "5")),
        max_update_bytes=int(os.getenv("MAX_UPDATE_BYTES", str(256 * 1024 * 1024))),
        regions_geojson_path=_optional_path("REGIONS_GEOJSON_PATH"),
        region_id_field=os.getenv("REGION_ID_FIELD", "region_id"),
        region_name_field=os.getenv("REGION_NAME_FIELD", "name"),
        region_population_field=os.getenv("REGION_POPULATION_FIELD", "population"),
        region_populations_csv=_optional_path("REGION_POPULATIONS_CSV"),
        region_population_source=os.getenv("REGION_POPULATION_SOURCE", "Census 2011"),
        ensemble_forecasts=_flag("ENSEMBLE_FORECASTS", True),
        surveillance_reports_csv=_optional_path("SURVEILLANCE_REPORTS_CSV"),
        suppression_threshold=int(os.getenv("SUPPRESSION_THRESHOLD", "5")),
        surveillance_weeks=int(os.getenv("SURVEILLANCE_WEEKS", "104")),
        simulation_end_week=_optional_monday("SIMULATION_END_WEEK"),
        cors_origins=_list("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"),
        api_base_url=os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/"),
    )
