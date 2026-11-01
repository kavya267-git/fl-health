"""Differential-privacy mechanism, accounting, suppression and validation checks."""

import math

import numpy as np
import pytest

from analytics.privacy import validation
from analytics.privacy.dp import (
    DPConfig,
    account_rounds,
    gaussian_rho,
    privatize_update,
    update_norm,
    zcdp_to_epsilon,
)
from analytics.privacy.suppression import suppress_small_count, violates_threshold


def _weights(scale):
    rng = np.random.default_rng(0)
    return {
        "layer.weight": (rng.standard_normal((40, 25)) * scale).astype(np.float32),
        "layer.bias": (rng.standard_normal(25) * scale).astype(np.float32),
        "bn.running_var": np.ones(25, dtype=np.float32),
        "bn.num_batches_tracked": np.array(3, dtype=np.int64),
    }


def test_disabled_dp_passes_weights_through_unchanged():
    base, local = _weights(0.0), _weights(1.0)
    sent, report = privatize_update(base, local, DPConfig(enabled=False), np.random.default_rng(0))
    assert all(np.array_equal(sent[k], local[k]) for k in local)
    assert report["enabled"] is False and report["mechanism"] == "none" and report["prototype"] is True


def test_update_is_clipped_to_the_norm_bound():
    base, local = _weights(0.0), _weights(1.0)
    config = DPConfig(enabled=True, clip_norm=1.0, noise_multiplier=1e-9)
    sent, report = privatize_update(base, local, config, np.random.default_rng(0))
    assert report["update_norm_before"] > 1.0 and report["clipped"] is True
    assert update_norm(base, sent) == pytest.approx(1.0, rel=1e-4)
    # Direction is preserved: the sent update is the original scaled down.
    ratio = sent["layer.weight"] / local["layer.weight"]
    assert np.allclose(ratio, ratio.flat[0], rtol=1e-3)


def test_small_updates_are_not_scaled_up():
    base, local = _weights(0.0), _weights(1e-4)
    sent, report = privatize_update(base, local, DPConfig(True, 1.0, 1e-9), np.random.default_rng(0))
    assert report["clipped"] is False
    assert np.allclose(sent["layer.weight"], local["layer.weight"], atol=1e-6)


def test_noise_has_the_configured_scale():
    base = _weights(0.0)
    config = DPConfig(enabled=True, clip_norm=2.0, noise_multiplier=0.5)
    sent, report = privatize_update(base, base, config, np.random.default_rng(1))  # zero update: output is pure noise
    assert report["noise_std"] == pytest.approx(1.0)
    noise = np.concatenate([sent["layer.weight"].ravel(), sent["layer.bias"].ravel()])
    assert noise.std() == pytest.approx(1.0, rel=0.08) and abs(noise.mean()) < 0.1


def test_statistics_buffers_are_left_alone_and_declared():
    base, local = _weights(0.0), _weights(1.0)
    local["bn.running_var"] = np.full(25, 2.0, dtype=np.float32)
    sent, report = privatize_update(base, local, DPConfig(True, 0.1, 5.0), np.random.default_rng(0))
    assert np.array_equal(sent["bn.running_var"], local["bn.running_var"])
    assert sent["bn.num_batches_tracked"] == 3
    assert report["unprotected_tensors"] == ["bn.num_batches_tracked", "bn.running_var"]
    assert report["noised_tensors"] == 2


def test_configuration_is_validated():
    with pytest.raises(ValueError):
        DPConfig(True, clip_norm=0, noise_multiplier=1).validate()
    with pytest.raises(ValueError):
        DPConfig(True, clip_norm=1, noise_multiplier=0).validate()
    DPConfig(False, clip_norm=0, noise_multiplier=0).validate()  # ignored when disabled
    assert DPConfig.from_dict(None).enabled is False


def test_accounting_follows_the_documented_formula():
    assert gaussian_rho(1.0) == 0.5 and gaussian_rho(2.0) == pytest.approx(0.125)
    assert zcdp_to_epsilon(0.5, 1e-5) == pytest.approx(0.5 + 2 * math.sqrt(0.5 * math.log(1e5)))
    rounds = [{"enabled": True, "noise_multiplier": 2.0}] * 4
    result = account_rounds(rounds, delta=1e-5)
    assert result["rho"] == pytest.approx(0.5)  # 4 rounds x 0.125 compose additively
    assert result["epsilon_over_dp_rounds"] == pytest.approx(zcdp_to_epsilon(0.5, 1e-5))
    assert result["bound_covers_all_rounds"] is True and result["prototype"] is True
    assert account_rounds(rounds * 2)["epsilon_over_dp_rounds"] > result["epsilon_over_dp_rounds"]


def test_a_round_without_dp_voids_the_overall_bound():
    result = account_rounds([{"enabled": True, "noise_multiplier": 1.0}, {"enabled": False}])
    assert result["rounds_with_dp"] == 1 and result["rounds_without_dp"] == 1
    assert result["bound_covers_all_rounds"] is False
    nothing = account_rounds([{"enabled": False}])
    assert nothing["epsilon_over_dp_rounds"] is None and nothing["bound_covers_all_rounds"] is False


def test_small_cell_suppression():
    assert suppress_small_count(0) == (0, False)
    assert suppress_small_count(3) == (None, True)
    assert suppress_small_count(5) == (5, False)
    assert suppress_small_count(2, threshold=2) == (2, False)
    assert violates_threshold(4) and not violates_threshold(0) and not violates_threshold(None)
    with pytest.raises(ValueError):
        suppress_small_count(-1)


def test_schema_check_flags_patient_level_columns():
    clean = {"hospitals": ["id", "name", "online"], "model_updates": ["id", "num_samples"]}
    assert validation.check_central_schema(clean)["status"] == validation.PASS
    leaky = {**clean, "uploads": ["id", "patient_id", "date_of_birth"]}
    result = validation.check_central_schema(leaky)
    assert result["status"] == validation.FAIL and "uploads.patient_id" in result["detail"]


def test_storage_separation_check(tmp_path):
    storage, hospitals = tmp_path / "models", tmp_path / "hospitals"
    storage.mkdir()
    hospitals.mkdir()
    (storage / "ehr_v0001.npz").write_bytes(b"x")
    assert validation.check_storage_separation(storage, hospitals)["status"] == validation.PASS
    (storage / "leak.csv").write_text("age,label\n1,0\n")
    assert validation.check_storage_separation(storage, hospitals)["status"] == validation.FAIL
    assert validation.check_storage_separation(hospitals / "inside", hospitals)["status"] == validation.FAIL


def test_remaining_checks_and_overall_status():
    assert validation.check_small_cells([0, 7, None, 12], 5)["status"] == validation.PASS
    assert validation.check_small_cells([0, 3], 5)["status"] == validation.FAIL
    assert validation.check_small_cells([], 5)["status"] == validation.INFO
    assert validation.check_differential_privacy([{"enabled": False}])["status"] == validation.WARN
    assert validation.check_differential_privacy([{"enabled": True}, {"enabled": True}])["status"] == validation.PASS
    assert validation.check_update_payloads([])["status"] == validation.INFO
    assert validation.check_transport("https://api.example.org", False)["status"] == validation.PASS
    assert validation.check_transport("http://api.example.org", False)["status"] == validation.WARN
    assert validation.overall_status([{"status": "PASS"}, {"status": "INFO"}]) == validation.PASS
    assert validation.overall_status([{"status": "PASS"}, {"status": "WARN"}]) == validation.WARN
    assert validation.overall_status([{"status": "WARN"}, {"status": "FAIL"}]) == validation.FAIL
