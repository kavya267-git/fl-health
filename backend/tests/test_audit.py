"""Audit trail: events recorded and tamper evidence."""

from app.services.audit_service import GENESIS_HASH
from backend_test_helpers import run_round


def test_round_produces_the_expected_audit_events(ctx):
    finished = run_round(ctx, "ehr")
    entries = ctx.audit.list_entries(round_id=finished["id"], limit=200)["items"]
    actions = [e["action"] for e in reversed(entries)]
    assert actions[0] == "FL_ROUND_CREATED"
    assert actions.count("HOSPITAL_JOINED_ROUND") == 4
    assert actions.count("LOCAL_UPDATE_RECEIVED") == 4
    assert (
        actions.index("AGGREGATION_STARTED")
        < actions.index("AGGREGATION_COMPLETED")
        < actions.index("GLOBAL_MODEL_CREATED")
    )
    assert "MODEL_ACCESSED" in actions
    assert actions[-1] == "FL_ROUND_COMPLETED"
    created = next(e for e in entries if e["action"] == "GLOBAL_MODEL_CREATED")
    assert created["model_version"] == "ehr v1"


def test_chain_links_every_entry_to_the_previous_one(ctx):
    run_round(ctx, "ecg")
    rows = ctx.db.fetch_all("SELECT * FROM audit_logs ORDER BY id")
    assert rows[0]["previous_hash"] == GENESIS_HASH
    for previous, current in zip(rows, rows[1:]):
        assert current["previous_hash"] == previous["current_hash"]
    result = ctx.audit.verify_chain()
    assert result["valid"] and result["entries_checked"] == len(rows)
    assert result["latest_hash"] == rows[-1]["current_hash"]


def test_modifying_an_entry_is_detected(ctx):
    run_round(ctx, "ecg")
    target = ctx.db.fetch_all("SELECT id FROM audit_logs ORDER BY id")[3]["id"]
    ctx.db.execute("UPDATE audit_logs SET actor = 'someone-else' WHERE id = :id", {"id": target})
    result = ctx.audit.verify_chain()
    assert not result["valid"] and result["first_invalid_id"] == target
    assert "modified" in result["reason"]


def test_deleting_an_entry_is_detected(ctx):
    run_round(ctx, "ecg")
    rows = ctx.db.fetch_all("SELECT id FROM audit_logs ORDER BY id")
    ctx.db.execute("DELETE FROM audit_logs WHERE id = :id", {"id": rows[2]["id"]})
    result = ctx.audit.verify_chain()
    assert not result["valid"] and result["first_invalid_id"] == rows[3]["id"]


def test_filters_and_search(ctx):
    run_round(ctx, "ehr")
    ctx.hospitals.set_online("hospital_b", False, "tester")
    by_action = ctx.audit.list_entries(action="LOCAL_UPDATE_RECEIVED")
    assert by_action["total"] == 4
    by_hospital = ctx.audit.list_entries(hospital_id="hospital_b")
    assert by_hospital["total"] >= 3 and all(e["hospital_id"] == "hospital_b" for e in by_hospital["items"])
    assert ctx.audit.list_entries(search="HOSPITAL_STATUS")["total"] == 1
    assert ctx.audit.list_entries(date_from="2999-01-01")["total"] == 0
    assert ctx.audit.list_entries(date_to="2000-01-01")["total"] == 0
    page = ctx.audit.list_entries(limit=5, offset=0)
    assert len(page["items"]) == 5 and page["total"] > 5
    assert page["items"][0]["id"] > page["items"][-1]["id"]  # newest first
