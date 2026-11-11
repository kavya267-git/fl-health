"""MODEL_WEIGHTS_IN_DATABASE: global model weights survive a host without a persistent disk."""

import shutil

from app.services.context import bootstrap, build_context
from backend_test_helpers import run_round


def test_rounds_work_and_weights_survive_losing_the_model_folder(settings):
    settings = settings.model_copy(update={"model_weights_in_database": True, "model_keep_versions": 2})
    ctx = build_context(settings)
    bootstrap(ctx)
    for _ in range(3):
        assert run_round(ctx, "ehr")["status"] == "COMPLETED"
    latest = ctx.registry.latest("ehr")
    assert latest["weights_path"] == f"db:ehr:v{latest['version']}"
    weights = ctx.registry.load_weights("ehr", latest["version"])
    ctx.close()

    # The host restarts with an empty disk: the weights come back from the database.
    shutil.rmtree(settings.model_storage_path)
    again = build_context(settings)
    bootstrap(again)
    restored = again.registry.load_weights("ehr", latest["version"])
    assert set(restored) == set(weights)
    assert all((restored[k] == weights[k]).all() for k in weights)
    # Only the newest MODEL_KEEP_VERSIONS keep their weights.
    rows = again.db.fetch_all("SELECT id FROM model_weights WHERE id LIKE :p", {"p": "ehr:%"})
    assert len(rows) == 2
    assert run_round(again, "ehr")["status"] == "COMPLETED"
    again.close()
