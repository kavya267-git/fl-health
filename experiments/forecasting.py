"""Surveillance forecasting backtest on the SIMULATED weekly series (protocol in the config).

    python -m experiments.forecasting experiments/configs/surveillance_forecasting.yaml
    python -m experiments.forecasting experiments/configs/surveillance_forecasting.yaml --report

The first form runs the backtest and writes experiments/results/<name>/ (forecasts.csv is large and not
committed; summary.csv, weights.csv, config.json and section.md are). ``--report`` only rewrites section.md
from the saved CSVs. Then ``python scripts/run_experiment.py --report`` puts section.md into RESULTS.md.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import warnings
from datetime import date
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

from analytics.forecasting.ensemble import residual_quantiles, simplex_weights
from analytics.forecasting.lstm import GlobalLSTM, LSTMSettings
from analytics.forecasting.models import (
    AutoRegressive,
    NaiveLastValue,
    ProphetForecaster,
    SeasonalAutoRegressive,
    SeasonalNaive,
    StatsmodelsARIMA,
)
from analytics.geospatial.regions import region_table, simulated_regions
from analytics.geospatial.surveillance import aggregate_regional, simulate_reports

RESULTS_DIR = Path(__file__).resolve().parent / "results"

MODEL_LABELS = {
    "naive": "Naive (last value)",
    "seasonal_naive": "Seasonal naive (52 weeks)",
    "arima_least_squares": "ARIMA(p,d,0), least squares",
    "seasonal_arima_least_squares": "Seasonal ARIMA(1,0,0)(0,1,0)[52], least squares",
    "arima_statsmodels": "ARIMA(2,1,1), statsmodels",
    "prophet": "Prophet",
    "lstm": "LSTM (global)",
    "ensemble": "Ensemble (ARIMA + Prophet + LSTM)",
}
SINGLE_SERIES = ("naive", "seasonal_naive", "arima_least_squares", "seasonal_arima_least_squares", "arima_statsmodels", "prophet")


def load_config(path: Path) -> dict:
    import yaml

    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


# ------------------------------------------------------------------ data
def build_series(data: dict) -> tuple[list[dict], list[str]]:
    """The 36 SIMULATED regional series: one per region and disease, NaN where a week has no total."""
    from ml.simulation.hospitals import SIMULATED_HOSPITALS

    regions = region_table(simulated_regions(seed=data["seed"] % 1000))  # as the demo does
    frame = simulate_reports(
        regions,
        [h.hospital_id for h in SIMULATED_HOSPITALS],
        date.fromisoformat(data["end_week"]),
        data["weeks"],
        data["seed"],
        data["suppression_threshold"],
    )
    regional = aggregate_regional(frame)
    weeks = sorted(regional["week_start"].unique())
    if len(weeks) != data["weeks"]:
        raise ValueError(f"Expected {data['weeks']} weeks, got {len(weeks)}")
    position = {week: index for index, week in enumerate(weeks)}
    series = []
    for (disease, region_id), group in regional.groupby(["disease", "region_id"], sort=True):
        values = np.full(len(weeks), np.nan)
        for week, count in zip(group["week_start"], group["case_count"]):
            if not pd.isna(count):
                values[position[week]] = float(count)
        series.append({"series_id": f"{disease}:{region_id}", "disease": disease, "region_id": region_id, "values": values})
    return series, weeks


def filled(history: np.ndarray) -> np.ndarray:
    """Fill missing weeks from the history itself (never from later weeks)."""
    history = np.asarray(history, dtype=np.float64)
    missing = np.isnan(history)
    if not missing.any():
        return history
    if missing.all():
        raise ValueError("no observed week")
    index = np.arange(len(history))
    out = history.copy()
    out[missing] = np.interp(index[missing], index[~missing], history[~missing])
    return out


def scale_of(values: np.ndarray, last_week: int) -> float:
    """Mean of the observed weeks 1..last_week, at least 1."""
    observed = values[:last_week]
    observed = observed[~np.isnan(observed)]
    return max(float(observed.mean()) if len(observed) else 1.0, 1.0)


def window_of(target_week: int, windows: dict) -> str | None:
    for name in ("validation", "test"):
        first, last = windows[name]
        if first <= target_week <= last:
            return name
    return None


def single_series_model(key: str, cfg: dict, start: str):
    if key == "naive":
        return NaiveLastValue()
    if key == "seasonal_naive":
        return SeasonalNaive(52)
    if key == "arima_least_squares":
        return AutoRegressive()
    if key == "seasonal_arima_least_squares":
        return SeasonalAutoRegressive(52)
    if key == "arima_statsmodels":
        return StatsmodelsARIMA((2, 1, 1))
    if key == "prophet":
        p = cfg["prophet"]
        return ProphetForecaster(start, p["yearly_seasonality"], p["uncertainty_samples"])
    raise ValueError(key)


# ------------------------------------------------------------------ backtest
def run(cfg: dict, out: Path) -> None:
    import torch

    threads = int(os.getenv("FL_EXPERIMENT_THREADS", "4"))
    torch.set_num_threads(threads)
    import logging

    for name in ("cmdstanpy", "prophet"):
        logging.getLogger(name).setLevel(logging.ERROR)
    windows = cfg["windows"]
    horizons = cfg["horizons"]
    max_h = max(horizons)
    fit_last = windows["fit"][1]
    all_series, weeks = build_series(cfg["data"])
    limit = cfg["data"]["max_missing_share_in_fit_window"]
    series = [s for s in all_series if np.isnan(s["values"][:fit_last]).mean() <= limit]
    excluded = [s["series_id"] for s in all_series if s not in series]
    print(f"{len(series)} of {len(all_series)} series x {len(weeks)} weeks (SIMULATED); excluded {excluded}")

    first_origin = windows["validation"][0] - max_h  # earliest origin with a scored target
    last_origin = windows["test"][1] - 1
    rows: List[dict] = []
    seconds: Dict[str, float] = {}
    failures: Dict[str, int] = {}

    def record(model: str, s: dict, origin: int, mean, lower, upper) -> None:
        for h in horizons:
            target = origin + h
            window = window_of(target, windows)
            if window is None or target > len(weeks):
                continue
            rows.append(
                {
                    "model": model,
                    "series_id": s["series_id"],
                    "origin_week": origin,
                    "horizon": h,
                    "target_week": target,
                    "window": window,
                    "actual": s["values"][target - 1],
                    "mean": max(float(mean[h - 1]), 0.0),
                    "lower": None if lower is None else max(float(lower[h - 1]), 0.0),
                    "upper": None if upper is None else max(float(upper[h - 1]), 0.0),
                }
            )

    lstm_settings = LSTMSettings(**cfg["lstm"])
    for origin in range(first_origin, last_origin + 1):  # origin = last observed week (1-based)
        started = time.time()
        histories = [filled(s["values"][:origin]) for s in series]
        for key in [m for m in cfg["models"] if m in SINGLE_SERIES]:
            t0 = time.time()
            for s, history in zip(series, histories):
                try:
                    with warnings.catch_warnings():  # statsmodels convergence chatter; failures are still counted
                        warnings.simplefilter("ignore")
                        model = single_series_model(key, cfg, weeks[0]).fit(history)
                        mean, lower, upper = model.interval80(max_h)
                    if not np.all(np.isfinite(mean)):
                        raise ValueError("non-finite forecast")
                except Exception:  # noqa: BLE001 - counted and reported, not hidden
                    failures[key] = failures.get(key, 0) + 1
                    continue
                record(key, s, origin, mean, lower, upper)
            seconds[key] = seconds.get(key, 0.0) + time.time() - t0
        if "lstm" in cfg["models"]:
            t0 = time.time()
            scales = [scale_of(s["values"], min(origin, fit_last)) for s in series]
            network = GlobalLSTM(lstm_settings, horizon=max_h).fit(histories, scales)
            for s, mean in zip(series, network.predict(histories, scales)):
                record("lstm", s, origin, mean, None, None)
            seconds["lstm"] = seconds.get("lstm", 0.0) + time.time() - t0
        print(f"origin week {origin}: {time.time() - started:.1f} s", flush=True)

    table = pd.DataFrame(rows)
    scales = {s["series_id"]: scale_of(s["values"], fit_last) for s in series}
    table["scale"] = table["series_id"].map(scales)
    level = cfg["interval_level"]

    # LSTM interval: quantiles of its scaled validation errors, per horizon.
    lstm_quantiles = {}
    for h in horizons:
        mask = (table["model"] == "lstm") & (table["horizon"] == h)
        val = table[mask & (table["window"] == "validation") & table["actual"].notna()]
        q_low, q_high = residual_quantiles((val["actual"] - val["mean"]) / val["scale"], level)
        lstm_quantiles[h] = (q_low, q_high)
        table.loc[mask, "lower"] = np.maximum(table.loc[mask, "mean"] + q_low * table.loc[mask, "scale"], 0.0)
        table.loc[mask, "upper"] = np.maximum(table.loc[mask, "mean"] + q_high * table.loc[mask, "scale"], 0.0)

    weight_rows = []
    if "ensemble" in cfg["models"]:
        members = cfg["ensemble"]["members"]
        key = ["series_id", "origin_week", "horizon"]
        wide = table[table["model"].isin(members)].pivot_table(index=key, columns="model", values="mean").dropna()
        info = table[table["model"] == members[0]].set_index(key)[["target_week", "window", "actual", "scale"]]
        wide = wide.join(info, how="inner")
        ensemble_rows = []
        for h in horizons:
            at_h = wide[wide.index.get_level_values("horizon") == h]
            val = at_h[(at_h["window"] == "validation") & at_h["actual"].notna()]
            weights = simplex_weights(
                val[members].to_numpy() / val["scale"].to_numpy()[:, None],
                (val["actual"] / val["scale"]).to_numpy(),
            )
            mean = np.clip(at_h[members].to_numpy() @ weights, 0.0, None)
            val_mean = np.clip(val[members].to_numpy() @ weights, 0.0, None)
            q_low, q_high = residual_quantiles((val["actual"].to_numpy() - val_mean) / val["scale"].to_numpy(), level)
            weight_rows.append({"horizon": h, **{m: float(w) for m, w in zip(members, weights)}, "validation_forecasts": len(val)})
            for (series_id, origin, _), m, row in zip(at_h.index, mean, at_h.itertuples()):
                ensemble_rows.append(
                    {
                        "model": "ensemble",
                        "series_id": series_id,
                        "origin_week": origin,
                        "horizon": h,
                        "target_week": row.target_week,
                        "window": row.window,
                        "actual": row.actual,
                        "mean": float(m),
                        "lower": max(float(m + q_low * row.scale), 0.0),
                        "upper": max(float(m + q_high * row.scale), 0.0),
                        "scale": row.scale,
                    }
                )
        table = pd.concat([table, pd.DataFrame(ensemble_rows)], ignore_index=True)

    out.mkdir(parents=True, exist_ok=True)
    table.to_csv(out / "forecasts.csv", index=False)
    pd.DataFrame(weight_rows).to_csv(out / "weights.csv", index=False)
    summary = summarise(table, cfg)
    summary.to_csv(out / "summary.csv", index=False)
    run_info = {
        "config": cfg,
        "series": len(series),
        "excluded_series": excluded,
        "weeks": [weeks[0], weeks[-1]],
        "origins": [first_origin, last_origin],
        "failed_fits": failures,
        "seconds": {k: round(v, 1) for k, v in seconds.items()},
        "lstm_interval_quantiles": {str(h): q for h, q in lstm_quantiles.items()},
        "torch_threads": threads,
        "simulated": True,
    }
    (out / "config.json").write_text(json.dumps(run_info, indent=2, default=str), encoding="utf-8")
    write_section(out)


# ------------------------------------------------------------------ scoring
def summarise(table: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Test-window metrics on the forecasts every model produced (so all models are scored on the same rows)."""
    test = table[(table["window"] == "test") & table["actual"].notna()]
    key = ["series_id", "origin_week", "horizon"]
    models = cfg["models"]
    counts = test.groupby(key)["model"].nunique()
    common = counts[counts == len(models)].index
    test = test.set_index(key).loc[common].reset_index()
    rows = []
    for h in [*cfg["horizons"], "all"]:
        at_h = test if h == "all" else test[test["horizon"] == h]
        base = at_h[at_h["model"] == "seasonal_naive"]
        base_mae = float(np.mean(np.abs(base["actual"] - base["mean"])))
        for model in models:
            m = at_h[at_h["model"] == model]
            error = m["actual"] - m["mean"]
            covered = (m["actual"] >= m["lower"]) & (m["actual"] <= m["upper"])
            mae = float(np.mean(np.abs(error)))
            rows.append(
                {
                    "model": model,
                    "horizon": h,
                    "forecasts": len(m),
                    "mae": mae,
                    "rmse": float(np.sqrt(np.mean(error**2))),
                    "coverage_80": float(covered.mean()),
                    "mae_ratio_vs_seasonal_naive": mae / base_mae if base_mae > 0 else float("nan"),
                }
            )
    return pd.DataFrame(rows)


def scope_note(cfg: dict, info: dict) -> str:
    """Which series the results apply to, described from the (deterministic) simulated data."""
    series, _ = build_series(cfg["data"])
    fit_last = cfg["windows"]["fit"][1]
    excluded = set(info["excluded_series"])

    def describe(group):
        missing = [float(np.isnan(s["values"][:fit_last]).mean()) for s in group]
        medians = [float(np.nanmedian(s["values"][:fit_last])) for s in group]
        return min(missing), max(missing), float(np.median(medians))

    kept = [s for s in series if s["series_id"] not in excluded]
    dropped = [s for s in series if s["series_id"] in excluded]
    k_lo, k_hi, k_med = describe(kept)
    d_lo, d_hi, d_med = describe(dropped)
    return (
        f"**These results apply to the {len(kept)} series with enough reported weeks, not to all "
        f"{len(series)}.** The {len(dropped)} excluded series were mostly suppressed small counts: "
        f"{d_lo:.0%}-{d_hi:.0%} of their weeks 1-{fit_last} have no regional total because a hospital's count "
        f"was below the suppression threshold, and their median weekly count is {d_med:.1f}, against "
        f"{k_lo:.0%}-{k_hi:.0%} missing and a median of {k_med:.1f} for the series that were forecast. How the "
        f"models would do on those sparse series was not measured."
    )


def write_section(out: Path) -> None:
    info = json.loads((out / "config.json").read_text(encoding="utf-8"))
    cfg = info["config"]
    summary = pd.read_csv(out / "summary.csv")
    weights = pd.read_csv(out / "weights.csv") if (out / "weights.csv").exists() else pd.DataFrame()
    lines = [f"### {cfg['title']}", "", cfg["description"].strip(), ""]
    lines.append(
        f"*Config:* `experiments/configs/{out.name}.yaml`. Data: {info['series']} SIMULATED series "
        f"({len(info['excluded_series'])} excluded by the missing-weeks rule: {', '.join(info['excluded_series']) or 'none'}), weeks "
        f"{info['weeks'][0]} to {info['weeks'][1]}. Origins: weeks {info['origins'][0]}-{info['origins'][1]}. "
        f"One run (LSTM seed {cfg['lstm']['seed']}, {info['torch_threads']} PyTorch threads)."
    )
    lines.append("")
    lines.append(scope_note(cfg, info))
    lines.append("")
    every = summary[summary["horizon"] == "all"]
    lines.append(
        f"Test window (targets in weeks {cfg['windows']['test'][0]}-{cfg['windows']['test'][1]}), horizons 1-4 pooled, "
        f"{int(every['forecasts'].iloc[0])} forecasts per model:"
    )
    lines.append("")
    lines.append("| Model | MAE | RMSE | 80% interval coverage | MAE ratio vs seasonal naive |")
    lines.append("| --- | --- | --- | --- | --- |")
    for row in every.itertuples():
        lines.append(
            f"| {MODEL_LABELS[row.model]} | {row.mae:.2f} | {row.rmse:.2f} | {row.coverage_80:.3f} | "
            f"{row.mae_ratio_vs_seasonal_naive:.3f} |"
        )
    lines.append("")
    lines.append("By horizon (MAE / 80% coverage / MAE ratio vs seasonal naive):")
    lines.append("")
    horizons = [h for h in summary["horizon"].unique() if h != "all"]
    lines.append("| Model | " + " | ".join(f"{h} week{'s' if str(h) != '1' else ''} ahead" for h in horizons) + " |")
    lines.append("| --- |" + " --- |" * len(horizons))
    for model in every["model"]:
        cells = []
        for h in horizons:
            r = summary[(summary["model"] == model) & (summary["horizon"] == h)].iloc[0]
            cells.append(f"{r.mae:.2f} / {r.coverage_80:.3f} / {r.mae_ratio_vs_seasonal_naive:.3f}")
        lines.append(f"| {MODEL_LABELS[model]} | " + " | ".join(cells) + " |")
    lines.append("")
    if not weights.empty:
        members = cfg["ensemble"]["members"]
        lines.append("Ensemble weights, fitted on the validation window only (each row sums to 1):")
        lines.append("")
        lines.append("| Horizon | " + " | ".join(MODEL_LABELS[m] for m in members) + " | Validation forecasts |")
        lines.append("| --- |" + " --- |" * (len(members) + 1))
        for row in weights.itertuples():
            cells = [f"{getattr(row, m):.3f}" for m in members]
            lines.append(f"| {row.horizon} | " + " | ".join(cells) + f" | {row.validation_forecasts} |")
        lines.append("")
    failed = {k: v for k, v in info["failed_fits"].items() if v}
    if failed:
        lines.append(
            "Fits that failed (counted per series and origin; a failed fit has no forecast, and only forecasts "
            "that every model produced are scored): "
            + ", ".join(f"{MODEL_LABELS[k]} {v}" for k, v in failed.items())
            + "."
        )
        lines.append("")
    lines.append(
        "Coverage is the share of test targets inside the 80% interval (0.8 is the target). Intervals: the "
        "models' own for the statistical models and Prophet; for the LSTM and the ensemble, the 10th and 90th "
        "percentiles of their scaled validation errors. All values come from the run above; nothing was tuned "
        "on the test window. The series are simulated, so this checks the forecasting pipeline, not real-world "
        "accuracy."
    )
    lines.append("")
    (out / "section.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("config", type=Path)
    parser.add_argument("--report", action="store_true", help="Only rewrite section.md from saved results")
    args = parser.parse_args()
    out = RESULTS_DIR / args.config.stem
    if args.report:
        write_section(out)
    else:
        run(load_config(args.config), out)
    print(f"Wrote {out / 'section.md'}")


if __name__ == "__main__":
    main()
