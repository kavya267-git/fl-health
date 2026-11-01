"""Database layer and schema."""

import pytest

from app.database import Database, DatabaseError
from app.models.tables import TABLES, create_statements


def test_schema_has_the_documented_tables(ctx):
    expected = {
        "users",
        "hospitals",
        "fl_rounds",
        "fl_participants",
        "model_registry",
        "model_updates",
        "training_metrics",
        "analytics_results",
        "forecasts",
        "audit_logs",
    }
    assert expected <= set(ctx.db.table_columns())
    assert expected <= set(TABLES)


def test_json_and_boolean_round_trip(tmp_path):
    db = Database(f"sqlite:///{(tmp_path / 'x.db').as_posix()}")
    db.create_schema()
    db.insert(
        "hospitals",
        {
            "id": "h1",
            "name": "Test",
            "kind": "x",
            "online": True,
            "modalities": ["ehr"],
            "data_summary": {"ehr": {"train_samples": 3}},
            "is_simulated": False,
            "created_at": "2024-01-01T00:00:00+00:00",
        },
    )
    row = db.fetch_one("SELECT * FROM hospitals WHERE id = :id", {"id": "h1"})
    assert row["online"] is True and row["is_simulated"] is False
    assert row["modalities"] == ["ehr"] and row["data_summary"]["ehr"]["train_samples"] == 3
    assert db.update("hospitals", {"online": False}, {"id": "h1"}) == 1
    assert db.fetch_one("SELECT online FROM hospitals WHERE id = :id", {"id": "h1"})["online"] is False


def test_transaction_rolls_back_on_error(tmp_path):
    db = Database(f"sqlite:///{(tmp_path / 'x.db').as_posix()}")
    db.create_schema()
    with pytest.raises(RuntimeError):
        with db.transaction():
            db.execute(
                "INSERT INTO regions (region_id, name, geometry, is_simulated) VALUES ('R1', 'x', '{}', :s)",
                {"s": True},
            )
            raise RuntimeError("boom")
    assert db.fetch_one("SELECT COUNT(*) AS n FROM regions")["n"] == 0


def test_unknown_columns_and_urls_are_rejected(tmp_path):
    db = Database(f"sqlite:///{(tmp_path / 'x.db').as_posix()}")
    db.create_schema()
    with pytest.raises(DatabaseError):
        db.insert("hospitals", {"id": "h1", "patient_name": "nope"})
    with pytest.raises(DatabaseError):
        Database("mysql://nope")


def test_postgres_ddl_uses_postgres_types():
    ddl = "\n".join(create_statements("postgres"))
    assert "JSONB" in ddl and "TIMESTAMPTZ" in ddl and "BIGSERIAL" in ddl
    assert "AUTOINCREMENT" not in ddl
    assert "patient" not in ddl.lower()
