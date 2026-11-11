"""EHR rounds use the class-weighted loss with the PyTorch models; other modalities and the NumPy models do not."""

from app.federated.coordinator import default_class_weighting


def test_default_class_weighting():
    assert default_class_weighting("ehr", "pytorch") == "balanced"
    assert default_class_weighting("ehr", "numpy-reference") == "none"  # not supported there
    assert default_class_weighting("ecg", "pytorch") == "none"
    assert default_class_weighting("xray", "pytorch") == "none"


def test_round_config_records_the_weighting(ctx):
    created = ctx.coordinator.start_round("ehr", ctx.hospitals.list_raw(), "tester")
    # The test suite uses the NumPy reference models, which train unweighted.
    assert created["config"]["training"]["class_weighting"] == "none"
    assert ctx.coordinator.node_round_info(created["id"])["training"]["class_weighting"] == "none"
    explicit = ctx.coordinator.start_round("ecg", ctx.hospitals.list_raw(), "tester", class_weighting="none")
    assert explicit["config"]["training"]["class_weighting"] == "none"
