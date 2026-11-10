"""Simulated missing values in an EHR round: the setting reaches the nodes, and is refused elsewhere."""

import pytest


def test_ehr_round_carries_the_missingness_setting_to_the_nodes(ctx):
    created = ctx.coordinator.start_round("ehr", ctx.hospitals.list_raw(), "tester", simulated_missing_rate=0.1)
    info = ctx.coordinator.node_round_info(created["id"])
    assert info["training"]["missingness"] == {"mcar_rate": 0.1, "seed": ctx.coordinator.default_seed}
    node = ctx.nodes.node("hospital_a")
    node.train_and_submit(created["id"], node.join(created["id"]))
    update = next(u for u in ctx.coordinator.updates(created["id"]) if u["hospital_id"] == "hospital_a")
    assert update["status"] != "REJECTED"


def test_rounds_without_the_setting_send_nothing_extra(ctx):
    created = ctx.coordinator.start_round("ehr", ctx.hospitals.list_raw(), "tester")
    assert "missingness" not in ctx.coordinator.node_round_info(created["id"])["training"]


@pytest.mark.parametrize("modality, rate, message", [("ecg", 0.1, "EHR rounds only"), ("ehr", 0.6, "between 0 and 0.5")])
def test_invalid_missingness_is_refused(ctx, modality, rate, message):
    with pytest.raises(Exception, match=message):
        ctx.coordinator.start_round(modality, ctx.hospitals.list_raw(), "tester", simulated_missing_rate=rate)
