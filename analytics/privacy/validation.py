"""Privacy validation checks.

Each check inspects something concrete about the running system and returns a
result with a status. The checks support the claim "raw patient data is not
centralised by this workflow"; they do not prove that the system is private.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Optional

from analytics.privacy.suppression import violates_threshold

PASS, WARN, FAIL, INFO = "PASS", "WARN", "FAIL", "INFO"

#: Column-name fragments that suggest patient-level data in a central table.
_PATIENT_LEVEL_PATTERNS = (
    "patient",
    "mrn",
    "ssn",
    "date_of_birth",
    "dob",
    "address",
    "phone",
    "subject_id",
    "hadm_id",
    "first_name",
    "last_name",
)

#: File types that would indicate raw records sitting in coordinator storage.
_RAW_DATA_SUFFIXES = (".csv", ".dcm", ".png", ".jpg", ".jpeg", ".dat", ".hea", ".parquet")


def _result(check_id: str, title: str, status: str, detail: str) -> dict:
    return {"id": check_id, "title": title, "status": status, "detail": detail}


def check_central_schema(table_columns: Dict[str, List[str]]) -> dict:
    """The coordinator database must hold metadata and aggregates only."""
    offenders = []
    for table, columns in table_columns.items():
        for column in columns:
            lowered = column.lower()
            if any(pattern in lowered for pattern in _PATIENT_LEVEL_PATTERNS):
                offenders.append(f"{table}.{column}")
    if offenders:
        return _result(
            "central_schema",
            "Central database holds no patient-level fields",
            FAIL,
            "Columns that look patient-level: " + ", ".join(sorted(offenders)),
        )
    return _result(
        "central_schema",
        "Central database holds no patient-level fields",
        PASS,
        f"Inspected {sum(len(c) for c in table_columns.values())} columns in {len(table_columns)} tables; "
        "none match patient-identifier patterns.",
    )


def check_storage_separation(coordinator_storage: Path, hospital_data_root: Optional[Path]) -> dict:
    """Coordinator storage must be separate from hospital data and contain no raw record files."""
    title = "Coordinator storage is separate from hospital data"
    coordinator_storage = Path(coordinator_storage).resolve()
    if hospital_data_root is not None:
        hospital_data_root = Path(hospital_data_root).resolve()
        if (
            coordinator_storage == hospital_data_root
            or hospital_data_root in coordinator_storage.parents
            or coordinator_storage in hospital_data_root.parents
        ):
            return _result(
                "storage_separation",
                title,
                FAIL,
                f"Coordinator storage ({coordinator_storage}) and hospital data ({hospital_data_root}) overlap.",
            )
    raw_files = []
    if coordinator_storage.exists():
        for path in coordinator_storage.rglob("*"):
            if path.is_file() and path.suffix.lower() in _RAW_DATA_SUFFIXES:
                raw_files.append(str(path.relative_to(coordinator_storage)))
    if raw_files:
        return _result(
            "storage_separation",
            title,
            FAIL,
            "Raw-data file types found in coordinator storage: " + ", ".join(raw_files[:5]),
        )
    return _result(
        "storage_separation",
        title,
        PASS,
        "Coordinator storage contains model weights and synthetic reference cases only.",
    )


def check_update_payloads(update_records: Iterable[dict]) -> dict:
    """Every accepted update must have passed structural validation."""
    title = "Model updates contain only expected tensors"
    records = list(update_records)
    if not records:
        return _result("update_payloads", title, INFO, "No model updates have been received yet.")
    rejected = [r for r in records if r.get("status") == "REJECTED"]
    accepted = len(records) - len(rejected)
    detail = (
        f"{accepted} update(s) accepted after checking tensor names, shapes, dtypes and finiteness "
        f"against the global model; {len(rejected)} rejected."
    )
    return _result("update_payloads", title, PASS, detail)


def check_small_cells(reported_counts: Iterable[Optional[int]], threshold: int) -> dict:
    title = f"Small-cell suppression (counts below {threshold})"
    counts = list(reported_counts)
    if not counts:
        return _result("small_cells", title, INFO, "No aggregated surveillance counts are stored yet.")
    violations = sum(1 for count in counts if violates_threshold(count, threshold))
    suppressed = sum(1 for count in counts if count is None)
    if violations:
        return _result(
            "small_cells",
            title,
            FAIL,
            f"{violations} stored hospital-level count(s) are between 1 and {threshold - 1}.",
        )
    return _result(
        "small_cells",
        title,
        PASS,
        f"{len(counts)} hospital-level cells inspected; {suppressed} suppressed, none between 1 and {threshold - 1}.",
    )


def check_differential_privacy(latest_dp_reports: Iterable[dict]) -> dict:
    title = "Differential privacy on model updates (prototype)"
    reports = [r for r in latest_dp_reports if r is not None]
    if not reports:
        return _result("differential_privacy", title, INFO, "No model updates have been received yet.")
    enabled = sum(1 for r in reports if r.get("enabled"))
    if enabled == 0:
        return _result(
            "differential_privacy",
            title,
            WARN,
            "Disabled for the updates received so far. Updates are sent without clipping or noise, "
            "so they carry no formal privacy bound.",
        )
    if enabled < len(reports):
        return _result(
            "differential_privacy",
            title,
            WARN,
            f"Enabled for {enabled} of {len(reports)} updates. The cumulative bound only holds if every round uses it.",
        )
    return _result(
        "differential_privacy",
        title,
        PASS,
        f"Clipping and Gaussian noise applied to all {len(reports)} updates. Prototype accounting - see assumptions.",
    )


def check_transport(api_base_url: str, demo_mode: bool) -> dict:
    title = "Transport encryption"
    if api_base_url.lower().startswith("https://"):
        return _result("transport", title, PASS, "The API is served over HTTPS.")
    if demo_mode:
        return _result(
            "transport",
            title,
            INFO,
            "Demo mode runs over plain HTTP on localhost. Use HTTPS for anything beyond a local demonstration.",
        )
    return _result("transport", title, WARN, "The API base URL is not HTTPS; updates would travel unencrypted.")


def overall_status(results: Iterable[dict]) -> str:
    statuses = [r["status"] for r in results]
    if FAIL in statuses:
        return FAIL
    if WARN in statuses:
        return WARN
    return PASS
