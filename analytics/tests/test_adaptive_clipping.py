"""Adaptive clipping (Andrew et al., NeurIPS 2021): budget split, noised bit, geometric clip-norm update."""

from __future__ import annotations

import math

import numpy as np
import pytest

from analytics.privacy.dp import DPConfig, account_rounds, gaussian_rho, next_clip_norm, privatize_update


def _weights(scale, seed=0):
    rng = np.random.default_rng(seed)
    return {
        "layer.weight": (rng.standard_normal((40, 25)) * scale).astype(np.float32),
        "bn.running_var": np.ones(25, dtype=np.float32),
    }


def _adaptive(z=0.5, share=0.1, clip=1.0, **extra):
    return DPConfig(enabled=True, clip_norm=clip, noise_multiplier=z, adaptive_clipping=True, quantile_budget_share=share, **extra)


@pytest.mark.parametrize("z", [0.001, 0.03, 0.1, 1.0, 3.0])
@pytest.mark.parametrize("share", [0.05, 0.1, 0.5])
def test_budget_split_matches_the_paper_and_totals_one_gaussian_round(z, share):
    config = _adaptive(z=z, share=share)
    sigma_b, z_update = config.bit_noise_std, config.update_noise_multiplier
    # Andrew et al. (2021): z_update = (z^-2 - (2 sigma_b)^-2)^(-1/2).
    assert z_update == pytest.approx((z**-2 - (2 * sigma_b) ** -2) ** -0.5)
    # Per round: update (sensitivity C, noise z_update C) + bit (sensitivity 1/2, noise sigma_b) = rho of z.
    rho = 1 / (2 * z_update**2) + (0.5**2) / (2 * sigma_b**2)
    assert rho == pytest.approx(gaussian_rho(z))
    # The share of the budget spent on the bit is the configured one.
    assert (0.5**2 / (2 * sigma_b**2)) / gaussian_rho(z) == pytest.approx(share)


def test_fixed_clipping_is_unchanged():
    config = DPConfig(enabled=True, clip_norm=1.0, noise_multiplier=0.5)
    assert config.update_noise_multiplier == 0.5
    _, report = privatize_update(_weights(0.0), _weights(1.0, 1), config, np.random.default_rng(0))
    assert "noisy_clip_bit" not in report and report["noise_std"] == pytest.approx(0.5)
    assert report["update_norm_before"] is not None


def test_report_carries_only_the_noised_bit():
    config = _adaptive(z=0.5, clip=1.0)
    _, report = privatize_update(_weights(0.0), _weights(1.0, 1), config, np.random.default_rng(0))
    assert report["adaptive_clipping"] is True
    # The raw norm and the clipped flag would reveal the bit; they are withheld.
    assert report["update_norm_before"] is None and report["clipped"] is None
    assert report["noise_multiplier"] == 0.5  # the round's total; accounting uses it
    assert report["noise_std"] == pytest.approx(config.update_noise_multiplier * 1.0)
    assert report["bit_noise_std"] == pytest.approx(config.bit_noise_std)
    assert isinstance(report["noisy_clip_bit"], float)


def test_noised_bit_is_centred_and_unbiased():
    big, small = _weights(1.0, 1), _weights(1e-4, 2)  # norm far above / far below a clip of 1
    config = _adaptive(z=0.2, clip=1.0)
    bits_big = [privatize_update(_weights(0.0), big, config, np.random.default_rng(s))[1]["noisy_clip_bit"] for s in range(400)]
    bits_small = [privatize_update(_weights(0.0), small, config, np.random.default_rng(s))[1]["noisy_clip_bit"] for s in range(400)]
    se = config.bit_noise_std / math.sqrt(400)
    assert abs(np.mean(bits_big) - (-0.5)) < 4 * se
    assert abs(np.mean(bits_small) - 0.5) < 4 * se
    assert np.std(bits_big) == pytest.approx(config.bit_noise_std, rel=0.15)


def test_accounting_is_the_same_as_fixed_clipping():
    adaptive = [privatize_update(_weights(0.0), _weights(1.0, s), _adaptive(z=0.3), np.random.default_rng(s))[1] for s in range(5)]
    fixed = [
        privatize_update(_weights(0.0), _weights(1.0, s), DPConfig(enabled=True, noise_multiplier=0.3), np.random.default_rng(s))[1]
        for s in range(5)
    ]
    assert account_rounds(adaptive)["rho"] == pytest.approx(account_rounds(fixed)["rho"])


def test_geometric_update():
    # Every update clipped (estimate 0): C grows by exp(eta * target).
    step = next_clip_norm(2.0, [-0.5, -0.5, -0.5, -0.5], target_quantile=0.5, learning_rate=0.2)
    assert step["clip_norm"] == pytest.approx(2.0 * math.exp(0.1))
    assert step["estimated_share_unclipped"] == pytest.approx(0.0)
    # None clipped (estimate 1): C shrinks.
    assert next_clip_norm(2.0, [0.5] * 4, 0.5, 0.2)["clip_norm"] == pytest.approx(2.0 * math.exp(-0.1))
    # At the target, C stays.
    assert next_clip_norm(2.0, [0.5, 0.5, -0.5, -0.5], 0.5, 0.2)["clip_norm"] == pytest.approx(2.0)
    assert next_clip_norm(2.0, [], 0.5, 0.2) == {"clip_norm": 2.0, "estimated_share_unclipped": None, "hospitals": 0}


def test_clip_norm_converges_to_the_target_quantile_without_noise_dominating():
    # Hospitals' update norms are fixed; with small noise the clip norm settles near their median.
    norms = np.array([2.0, 4.0, 6.0, 8.0])
    config = _adaptive(z=0.01, clip=0.5)
    rng = np.random.default_rng(0)
    clip = config.clip_norm
    for _ in range(300):
        bits = [(1.0 if n <= clip else 0.0) - 0.5 + rng.normal(0, config.bit_noise_std) for n in norms]
        clip = next_clip_norm(clip, bits, 0.5, 0.2)["clip_norm"]
    assert 3.5 <= clip <= 7.0


@pytest.mark.parametrize(
    "field, value",
    [("target_quantile", 0.0), ("target_quantile", 1.0), ("clip_learning_rate", 0.0), ("quantile_budget_share", 1.0)],
)
def test_invalid_settings_are_refused(field, value):
    with pytest.raises(ValueError):
        DPConfig.from_dict({"enabled": True, "noise_multiplier": 0.1, "adaptive_clipping": True, field: value}).validate()


def test_round_trip_through_dict():
    config = _adaptive(z=0.1, share=0.2, target_quantile=0.7, clip_learning_rate=0.3)
    assert DPConfig.from_dict(config.to_dict()) == config
