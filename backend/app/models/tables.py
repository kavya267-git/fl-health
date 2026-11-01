"""Central database schema.

One definition, rendered for SQLite (local demo) and PostgreSQL (Supabase).
The coordinator stores metadata, metrics, aggregated analytics and audit
records. It has no table for patient-level data, by design.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

# (column name, logical type, extra SQL)
Column = Tuple[str, str, str]

TABLES: Dict[str, List[Column]] = {
    "users": [
        ("id", "text", "PRIMARY KEY"),
        ("email", "text", "NOT NULL UNIQUE"),
        ("display_name", "text", ""),
        ("role", "text", "NOT NULL"),
        ("hospital_id", "text", ""),
        ("created_at", "timestamp", "NOT NULL"),
        ("last_login_at", "timestamp", ""),
    ],
    # Passwords of accounts created through the sign-up form (demo provider only).
    # With Supabase configured, credentials live in Supabase Auth and this stays empty.
    "local_credentials": [
        ("user_id", "text", "PRIMARY KEY"),
        ("password_hash", "text", "NOT NULL"),
        ("updated_at", "timestamp", "NOT NULL"),
    ],
    "hospitals": [
        ("id", "text", "PRIMARY KEY"),
        ("name", "text", "NOT NULL"),
        ("kind", "text", ""),
        ("online", "boolean", "NOT NULL"),
        ("modalities", "json", "NOT NULL"),
        ("data_summary", "json", ""),
        ("is_simulated", "boolean", "NOT NULL"),
        ("last_activity_at", "timestamp", ""),
        ("created_at", "timestamp", "NOT NULL"),
    ],
    "fl_rounds": [
        ("id", "text", "PRIMARY KEY"),
        ("round_number", "integer", "NOT NULL"),
        ("modality", "text", "NOT NULL"),
        ("status", "text", "NOT NULL"),
        ("config", "json", "NOT NULL"),
        ("base_model_version", "integer", "NOT NULL"),
        ("result_model_version", "integer", ""),
        ("num_participants", "integer", "NOT NULL"),
        ("aggregation_status", "text", "NOT NULL"),
        ("global_metrics", "json", ""),
        ("error", "text", ""),
        ("created_by", "text", ""),
        ("is_simulated", "boolean", "NOT NULL"),
        ("started_at", "timestamp", "NOT NULL"),
        ("ended_at", "timestamp", ""),
    ],
    "fl_participants": [
        ("id", "text", "PRIMARY KEY"),
        ("round_id", "text", "NOT NULL"),
        ("hospital_id", "text", "NOT NULL"),
        ("status", "text", "NOT NULL"),
        ("num_samples", "integer", ""),
        ("local_metrics", "json", ""),
        ("evaluation", "json", ""),
        ("error", "text", ""),
        ("joined_at", "timestamp", ""),
        ("update_received_at", "timestamp", ""),
        ("evaluated_at", "timestamp", ""),
    ],
    "model_registry": [
        ("id", "text", "PRIMARY KEY"),
        ("modality", "text", "NOT NULL"),
        ("version", "integer", "NOT NULL"),
        ("architecture", "text", "NOT NULL"),
        ("backend", "text", "NOT NULL"),
        ("architecture_signature", "text", "NOT NULL"),
        ("num_parameters", "integer", "NOT NULL"),
        ("round_id", "text", ""),
        ("status", "text", "NOT NULL"),
        ("weights_path", "text", ""),
        ("weights_sha256", "text", "NOT NULL"),
        ("size_bytes", "integer", "NOT NULL"),
        ("metrics", "json", ""),
        ("dataset", "json", ""),
        ("is_simulated", "boolean", "NOT NULL"),
        ("created_at", "timestamp", "NOT NULL"),
    ],
    "model_updates": [
        ("id", "text", "PRIMARY KEY"),
        ("round_id", "text", "NOT NULL"),
        ("hospital_id", "text", "NOT NULL"),
        ("modality", "text", "NOT NULL"),
        ("architecture_signature", "text", ""),
        ("num_samples", "integer", ""),
        ("weights_sha256", "text", ""),
        ("size_bytes", "integer", ""),
        ("update_norm", "real", ""),
        ("dp_report", "json", ""),
        ("status", "text", "NOT NULL"),
        ("rejection_reason", "text", ""),
        ("storage_path", "text", ""),
        ("received_at", "timestamp", "NOT NULL"),
    ],
    "training_metrics": [
        ("id", "serial", "PRIMARY KEY"),
        ("round_id", "text", "NOT NULL"),
        ("modality", "text", "NOT NULL"),
        ("model_version", "integer", ""),
        ("scope", "text", "NOT NULL"),
        ("hospital_id", "text", ""),
        ("split", "text", "NOT NULL"),
        ("metrics", "json", "NOT NULL"),
        ("num_samples", "integer", ""),
        ("created_at", "timestamp", "NOT NULL"),
    ],
    "analytics_results": [
        ("id", "serial", "PRIMARY KEY"),
        ("kind", "text", "NOT NULL"),
        ("result_key", "text", "NOT NULL"),
        ("payload", "json", "NOT NULL"),
        ("model_version", "integer", ""),
        ("is_simulated", "boolean", "NOT NULL"),
        ("generated_at", "timestamp", "NOT NULL"),
    ],
    "forecasts": [
        ("id", "serial", "PRIMARY KEY"),
        ("region_id", "text", "NOT NULL"),
        ("disease", "text", "NOT NULL"),
        ("horizon", "integer", "NOT NULL"),
        ("model_name", "text", "NOT NULL"),
        ("payload", "json", "NOT NULL"),
        ("data_through", "text", "NOT NULL"),
        ("is_simulated", "boolean", "NOT NULL"),
        ("generated_at", "timestamp", "NOT NULL"),
    ],
    "audit_logs": [
        ("id", "serial", "PRIMARY KEY"),
        ("timestamp", "timestamp", "NOT NULL"),
        ("actor", "text", "NOT NULL"),
        ("action", "text", "NOT NULL"),
        ("hospital_id", "text", ""),
        ("round_id", "text", ""),
        ("model_version", "text", ""),
        ("status", "text", "NOT NULL"),
        ("details", "json", ""),
        ("previous_hash", "text", "NOT NULL"),
        ("current_hash", "text", "NOT NULL"),
    ],
    "regions": [
        ("region_id", "text", "PRIMARY KEY"),
        ("name", "text", "NOT NULL"),
        ("population", "integer", ""),
        ("geometry", "json", "NOT NULL"),
        ("centroid_lon", "real", ""),
        ("centroid_lat", "real", ""),
        ("neighbours", "json", ""),
        ("is_simulated", "boolean", "NOT NULL"),
    ],
    "surveillance_reports": [
        ("id", "serial", "PRIMARY KEY"),
        ("hospital_id", "text", "NOT NULL"),
        ("region_id", "text", "NOT NULL"),
        ("disease", "text", "NOT NULL"),
        ("week_start", "text", "NOT NULL"),
        ("case_count", "integer", ""),
        ("suppressed", "boolean", "NOT NULL"),
        ("is_simulated", "boolean", "NOT NULL"),
    ],
    # Latest heartbeat from each external hospital node: software and machine
    # facts plus record counts. Never records.
    "node_heartbeats": [
        ("hospital_id", "text", "PRIMARY KEY"),
        ("hostname", "text", ""),
        ("ml_backend", "text", ""),
        ("device", "text", ""),
        ("software_version", "text", ""),
        ("architectures", "json", ""),
        ("data_summary", "json", ""),
        ("connected_since", "timestamp", "NOT NULL"),
        ("last_seen_at", "timestamp", "NOT NULL"),
    ],
    # Per-hospital settings an operator controls. A separate table (not hospital columns) so that
    # existing databases pick it up: the schema is created with CREATE TABLE IF NOT EXISTS.
    "hospital_settings": [
        ("hospital_id", "text", "PRIMARY KEY"),
        ("participating", "boolean", "NOT NULL"),
        ("updated_at", "timestamp", "NOT NULL"),
        ("updated_by", "text", ""),
    ],
}

UNIQUE_INDEXES = {
    "fl_participants": [("round_id", "hospital_id")],
    "model_registry": [("modality", "version")],
    "analytics_results": [("kind", "result_key")],
    "forecasts": [("region_id", "disease", "horizon")],
    "surveillance_reports": [("hospital_id", "region_id", "disease", "week_start")],
}

INDEXES = {
    "fl_rounds": [("modality", "round_number")],
    "training_metrics": [("round_id",), ("modality", "scope")],
    "model_updates": [("round_id",)],
    "audit_logs": [("timestamp",), ("action",)],
    "surveillance_reports": [("disease", "week_start")],
}

_SQLITE_TYPES = {
    "text": "TEXT",
    "integer": "INTEGER",
    "real": "REAL",
    "boolean": "INTEGER",
    "json": "TEXT",
    "timestamp": "TEXT",
    "serial": "INTEGER",
}
_POSTGRES_TYPES = {
    "text": "TEXT",
    "integer": "BIGINT",
    "real": "DOUBLE PRECISION",
    "boolean": "BOOLEAN",
    "json": "JSONB",
    "timestamp": "TIMESTAMPTZ",
    "serial": "BIGSERIAL",
}

#: column name -> logical type, used to decode rows. A column name must mean
#: the same type in every table.
COLUMN_TYPES: Dict[str, str] = {}
_DECODED_KINDS = {"json", "boolean"}
for _table, _columns in TABLES.items():
    for _name, _kind, _extra in _columns:
        _previous = COLUMN_TYPES.setdefault(_name, _kind)
        if _previous != _kind and (_previous in _DECODED_KINDS or _kind in _DECODED_KINDS):
            raise RuntimeError(f"Column '{_name}' has conflicting types across tables")
TABLE_COLUMNS: Dict[str, List[str]] = {table: [c[0] for c in columns] for table, columns in TABLES.items()}


def create_statements(dialect: str) -> List[str]:
    """DDL for every table and index (``dialect`` is 'sqlite' or 'postgres')."""
    types = _SQLITE_TYPES if dialect == "sqlite" else _POSTGRES_TYPES
    statements = []
    for table, columns in TABLES.items():
        parts = []
        for name, kind, extra in columns:
            if kind == "serial" and dialect == "sqlite":
                parts.append(f"{name} INTEGER PRIMARY KEY AUTOINCREMENT")
            else:
                parts.append(f"{name} {types[kind]} {extra}".strip())
        statements.append(f"CREATE TABLE IF NOT EXISTS {table} (\n    " + ",\n    ".join(parts) + "\n)")
    for table, groups in UNIQUE_INDEXES.items():
        for columns in groups:
            name = f"uq_{table}_{'_'.join(columns)}"
            statements.append(f"CREATE UNIQUE INDEX IF NOT EXISTS {name} ON {table} ({', '.join(columns)})")
    for table, groups in INDEXES.items():
        for columns in groups:
            name = f"ix_{table}_{'_'.join(columns)}"
            statements.append(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({', '.join(columns)})")
    return statements
