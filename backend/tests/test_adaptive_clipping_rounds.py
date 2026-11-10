"""Adaptive clipping in platform rounds: the clip norm carries over from one finished adaptive round to the next."""

import math

from analytics.privacy.dp import DPConfig
from backend_test_helpers import run_round


def _dp(clip=0.5):
    return DPConfig(enabled=True, clip_norm=clip, noise_multiplier=0.01, adaptive_clipping=True)


def test_clip_norm_is_updated_from_noised_bits_and_used_by_the_next_round(ctx):
    first = run_round(ctx, "ehr", dp=_dp())
    assert first["status"] == "COMPLETED"
    dp = first["config"]["differential_privacy"]
    assert dp["clip_norm"] == 0.5 and dp["adaptive_clipping"] is True
    reports = [u["dp_report"] for u in ctx.coordinator.updates(first["id"])]
    assert all(r["update_norm_before"] is None and r["clipped"] is None for r in reports)
    bits = [r["noisy_clip_bit"] for r in reports]
    expected = 0.5 * math.exp(-0.2 * (sum(bits) / len(bits) + 0.5 - 0.5))
    assert dp["next_clip_norm"] == expected
    assert dp["estimated_share_unclipped"] == sum(bits) / len(bits) + 0.5

    # The next adaptive round starts from that value, whatever starting value is requested.
    second = run_round(ctx, "ehr", dp=_dp(clip=9.0))
    assert second["config"]["differential_privacy"]["clip_norm"] == expected


def test_fixed_rounds_do_not_adapt(ctx):
    finished = run_round(ctx, "ehr", dp=DPConfig(enabled=True, clip_norm=0.5, noise_multiplier=0.01))
    assert "next_clip_norm" not in finished["config"]["differential_privacy"]


def test_adaptive_rounds_of_another_modality_are_independent(ctx):
    run_round(ctx, "ehr", dp=_dp())
    ecg = ctx.coordinator.start_round("ecg", ctx.hospitals.list_raw(), "tester", dp=_dp(clip=2.0))
    assert ecg["config"]["differential_privacy"]["clip_norm"] == 2.0
