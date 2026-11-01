"""Tables and figures from the CSVs written by ``experiments.harness``.

Nothing here computes a model metric: every number comes from
``results/<experiment>/rounds.csv``. Means and standard deviations are over
seeds (sample standard deviation, n - 1).
"""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from experiments.harness import CLASS_SHORT, RESULTS_DIR, ROOT  # noqa: E402

METHOD_LABEL = {"local": "Local only", "fedavg": "FedAvg", "centralised": "Centralised (upper bound)"}
CLASS_LABEL = {
    "ecg": {"N": "N", "S": "S", "V": "V", "F": "F"},
    "ehr": {"neg": "no adverse outcome", "pos": "adverse outcome"},
    "xray": {"no_finding": "no finding", "finding": "finding"},
}
COLORS = {"local": "#b0751a", "fedavg": "#0f6e64", "centralised": "#5b5f97"}


# ------------------------------------------------------------------ loading
def read_rounds(name: str) -> List[dict]:
    path = RESULTS_DIR / name / "rounds.csv"
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        for key, value in list(row.items()):
            if key in ("experiment", "variant", "method", "modality", "source"):
                continue
            try:
                row[key] = float(value) if value not in ("", None) else None
            except ValueError:
                pass
    return rows


def read_config(name: str) -> dict:
    return json.loads((RESULTS_DIR / name / "config.json").read_text())


def runs(rows: List[dict]) -> Dict[tuple, List[dict]]:
    """(variant, method, seed) -> that run's rows in round order."""
    grouped: Dict[tuple, List[dict]] = defaultdict(list)
    for row in rows:
        grouped[(row["variant"], row["method"], row["seed"])].append(row)
    for key in grouped:
        grouped[key].sort(key=lambda r: r["round"])
    return grouped


def finals(rows: List[dict]) -> Dict[tuple, List[dict]]:
    """(variant, method) -> final-round row of every seed."""
    out: Dict[tuple, List[dict]] = defaultdict(list)
    for (variant, method, _seed), run_rows in runs(rows).items():
        out[(variant, method)].append(run_rows[-1])
    return out


# ------------------------------------------------------------- formatting
def mean_std(values: List[Optional[float]]) -> tuple:
    values = [v for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))]
    if not values:
        return None, None, 0
    if any(math.isinf(v) for v in values):  # epsilon without DP: no bound
        return math.inf, 0.0, len(values)
    arr = np.asarray(values, dtype=float)
    return float(arr.mean()), float(arr.std(ddof=1)) if len(arr) > 1 else 0.0, len(arr)


def fmt(values: List[Optional[float]], digits: int = 3) -> str:
    mean, std, n = mean_std(values)
    if mean is None:
        return "-"
    if math.isinf(mean):
        return "∞"
    return f"{mean:.{digits}f} ± {std:.{digits}f}"


def table(header: List[str], body: List[List[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in body]
    return "\n".join(lines)


def variant_order(config: dict) -> List[str]:
    return [v["label"] for v in config["config"]["variants"]]


# ---------------------------------------------------------------- metrics
def metric_columns(modality: str) -> List[tuple]:
    columns = [("macro_f1", "Macro-F1"), ("accuracy", "Accuracy")]
    if modality == "ehr" or modality == "xray":
        columns.append(("f1_pos", "F1 (positive)"))
    columns += [(f"recall_{c}", f"Recall {CLASS_LABEL[modality][c]}") for c in CLASS_SHORT[modality]]
    return columns


def rounds_to(run_rows: List[dict], target: Optional[float]) -> Optional[float]:
    if target is None:
        return None
    for row in run_rows:
        if row["macro_f1"] >= target:
            return row["round"]
    return math.inf


def fmt_rounds(values: List[Optional[float]]) -> str:
    values = [v for v in values if v is not None]
    if not values:
        return "-"
    reached = [v for v in values if not math.isinf(v)]
    if not reached:
        return f"not reached (0/{len(values)})"
    text = fmt(reached, 1)
    return text if len(reached) == len(values) else f"{text} ({len(reached)}/{len(values)} seeds)"


# ------------------------------------------------------------------ figures
def figure_curves(name: str, rows: List[dict], config: dict, modality: str) -> str:
    grouped = runs(rows)
    variants = variant_order(config)
    fig, axes = plt.subplots(1, len(variants), figsize=(4.2 * len(variants), 3.2), sharey=True, squeeze=False)
    for ax, variant in zip(axes[0], variants):
        for method in ("local", "fedavg", "centralised"):
            curves = [r for (v, m, _), r in grouped.items() if v == variant and m == method]
            if not curves:
                continue
            length = min(len(c) for c in curves)
            values = np.array([[row["macro_f1"] for row in c[:length]] for c in curves])
            x = np.arange(1, length + 1)
            mean, std = values.mean(axis=0), values.std(axis=0, ddof=1) if len(values) > 1 else 0
            ax.plot(x, mean, color=COLORS[method], label=METHOD_LABEL[method])
            ax.fill_between(x, mean - std, mean + std, color=COLORS[method], alpha=0.15, linewidth=0)
        ax.set_title(variant, fontsize=10)
        ax.set_xlabel("Round")
        ax.grid(alpha=0.3)
    axes[0][0].set_ylabel("Macro-F1 (held-out, pooled)")
    axes[0][-1].legend(fontsize=8, loc="lower right")
    fig.tight_layout()
    path = RESULTS_DIR / name / "curves.png"
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path.relative_to(ROOT / "experiments").as_posix()


def figure_privacy(name: str, rows: List[dict], config: dict) -> str:
    final = finals(rows)
    fig, ax = plt.subplots(figsize=(5, 3.4))
    for variant in variant_order(config):
        seeds = final.get((variant, "fedavg"), [])
        if not seeds:
            continue
        eps = seeds[0]["epsilon"]
        f1, std, _ = mean_std([r["macro_f1"] for r in seeds])
        x = eps if eps is not None and not math.isinf(eps) else None
        if x is None:
            ax.axhline(f1, color="#666", linestyle="--", linewidth=1, label=f"{variant} (no DP)")
        else:
            ax.errorbar([x], [f1], yerr=[std], fmt="o", capsize=3, label=variant)
    ax.set_xscale("log")
    ax.set_xlabel("ε after the last round (δ = 1e-5, platform accounting)")
    ax.set_ylabel("Macro-F1 (held-out, pooled)")
    ax.grid(alpha=0.3, which="both")
    ax.legend(fontsize=8)
    fig.tight_layout()
    path = RESULTS_DIR / name / "privacy.png"
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path.relative_to(ROOT / "experiments").as_posix()


def figure_bars(name: str, rows: List[dict], config: dict) -> str:
    final = finals(rows)
    variants = variant_order(config)
    methods = [m for m in ("local", "fedavg", "centralised") if any((v, m) in final for v in variants)]
    fig, ax = plt.subplots(figsize=(1.6 + 1.5 * len(variants), 3.4))
    width = 0.8 / len(methods)
    for i, method in enumerate(methods):
        stats = [mean_std([r["macro_f1"] for r in final.get((v, method), [])]) for v in variants]
        x = np.arange(len(variants)) + (i - (len(methods) - 1) / 2) * width
        ax.bar(x, [s[0] or 0 for s in stats], width, yerr=[s[1] or 0 for s in stats], capsize=3,
               color=COLORS[method], label=METHOD_LABEL[method])
    ax.set_xticks(np.arange(len(variants)), variants)
    ax.set_ylabel("Final macro-F1 (held-out, pooled)")
    ax.set_ylim(0, 1)
    ax.grid(alpha=0.3, axis="y")
    ax.legend(fontsize=8)
    fig.tight_layout()
    path = RESULTS_DIR / name / "final_f1.png"
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path.relative_to(ROOT / "experiments").as_posix()


# ------------------------------------------------------------------ summary
# "seconds" is left out: runs shared the CPU, so their wall-clock times are not comparable.
_NOT_METRICS = {"experiment", "variant", "method", "seed", "modality", "source", "round", "seconds"}


def write_summary(name: str, rows: List[dict]) -> Path:
    """Final round of every run, as mean and sample std over seeds: results/<name>/summary.csv.

    The small, committable digest of rounds.csv (which keeps every round of every run).
    """
    final = finals(rows)
    metrics = sorted(
        {k for rs in final.values() for r in rs for k, v in r.items() if k not in _NOT_METRICS and isinstance(v, float)}
    )
    out_rows = []
    for (variant, method), seeds_rows in final.items():
        row = {"experiment": name, "variant": variant, "method": method, "seeds": len(seeds_rows),
               "rounds": int(seeds_rows[0]["round"])}
        for metric in metrics:
            mean, std, n = mean_std([r.get(metric) for r in seeds_rows])
            row[f"{metric}_mean"] = "" if mean is None else mean
            row[f"{metric}_std"] = "" if std is None else std
        out_rows.append(row)
    path = RESULTS_DIR / name / "summary.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(out_rows[0]))
        writer.writeheader()
        writer.writerows(out_rows)
    return path


# ------------------------------------------------------------------ section
def section(name: str) -> str:
    rows = read_rounds(name)
    if not rows:
        return f"### {name}\n\nNo results yet.\n"
    write_summary(name, rows)
    config = read_config(name)
    settings = config["config"]
    modality = rows[0]["modality"]
    grouped, final = runs(rows), finals(rows)
    variants = variant_order(config)
    seeds = sorted({r["seed"] for r in rows})
    training = settings["training"]
    lines = [f"### {settings.get('title', name)}", ""]
    if settings.get("description"):
        lines += [settings["description"].strip(), ""]
    lines += [
        f"*Config:* `experiments/configs/{settings.get('config_file', name)}`. "
        f"Data: {settings['dataset']['source']} {modality.upper()}"
        + (f", stratified subsample of {settings['dataset']['max_records']} records" if settings["dataset"].get("max_records") else "")
        + f". Partition: {settings['partition']['scheme']}"
        + (f" (alpha = {settings['partition']['alpha']})" if settings["partition"]["scheme"] == "dirichlet" else "")
        + f". {int(training['rounds'])} rounds × {training['local_epochs']} local epochs, batch {training['batch_size']}, "
        f"learning rate {training['learning_rate']}. Seeds: {', '.join(str(int(s)) for s in seeds)}. "
        "Values are mean ± std over seeds, final round, held-out splits pooled over hospitals.",
        "",
    ]
    dataset_file = RESULTS_DIR / name / "dataset.json"
    if dataset_file.exists():
        pool = json.loads(dataset_file.read_text())

        def counts(key: str) -> str:
            return ", ".join(f"{c} {n:,}" for c, n in zip(pool["classes"], pool[key]))

        text = (
            f"Records available in {' + '.join(pool['files'])} (class Q dropped): "
            f"{pool['records_available']:,} ({counts('class_counts_available')})."
        )
        if pool.get("subsample"):
            sample = pool["subsample"]
            text += (
                f" Used: {pool['records_used']:,} ({counts('class_counts_used')}), a {sample['method']} subsample "
                f"drawn once with seed {sample['subsample_seed']} and shared by every MIT-BIH experiment and seed."
            )
        lines += [text, ""]

    columns = metric_columns(modality)
    held_out = "DS2" if settings["partition"]["scheme"] == "records" else "held-out data"
    result_rows = []  # (variant, label, prefix, rows)
    for variant in variants:
        for method in ("local", "fedavg", "centralised"):
            seeds_rows = final.get((variant, method))
            if not seeds_rows:
                continue
            if method == "local":
                result_rows.append((variant, "Local only, own hospital's share", "", seeds_rows))
                if any(r.get("cross_macro_f1") is not None for r in seeds_rows):
                    result_rows.append((variant, f"Local only, all hospitals' {held_out}", "cross_", seeds_rows))
            else:
                result_rows.append((variant, METHOD_LABEL[method], "", seeds_rows))
    body = [
        [variant, label, str(len(rs))] + [fmt([r.get(prefix + col) for r in rs]) for col, _ in columns]
        for variant, label, prefix, rs in result_rows
    ]
    lines += [table(["Variant", "Method", "Seeds"] + [label for _, label in columns], body), ""]
    if any(prefix for _, _, prefix, _ in result_rows):
        lines += [
            f"*Local only, all hospitals' {held_out}*: each hospital's final local model scored on every hospital's "
            "held-out records, pooled over the four models. It answers whether one hospital's model generalises to "
            "the other hospitals' patients. A dash means the metric was not recorded for that run.",
            "",
        ]

    if modality == "ecg" and any(r.get("precision_S") is not None for _, _, _, rs in result_rows for r in rs):
        body = [
            [variant, label]
            + [fmt([r.get(prefix + key) for r in rs]) for key in ("recall_S", "precision_S", "recall_V", "precision_V")]
            for variant, label, prefix, rs in result_rows
        ]
        lines += [
            "Sensitivity (Se, = recall) and positive predictivity (+P, = precision) for the S and V classes, the "
            "measures the inter-patient literature reports:",
            "",
            table(["Variant", "Method", "Se S", "+P S", "Se V", "+P V"], body),
            "",
        ]

    if any(m == "fedavg" for (_, m) in final):
        if any(r.get("epsilon") is not None and not math.isinf(r["epsilon"]) for rs in final.values() for r in rs):
            body = []
            for variant in variants:
                rs = final.get((variant, "fedavg"))
                if rs:
                    body.append([variant, fmt([r["epsilon"] for r in rs], 2), fmt([r["macro_f1"] for r in rs]),
                                 fmt([r["accuracy"] for r in rs]), fmt([r["median_update_norm"] for r in rs], 2),
                                 fmt([r["clipped_share"] for r in rs], 2)])
            lines += [
                "Privacy accounting (platform's zCDP bound, per hospital, over all rounds):",
                "",
                table(["Variant", "ε", "Macro-F1", "Accuracy", "Median update norm before clipping",
                       "Share of updates clipped"], body),
                "",
                f"![F1 against epsilon]({figure_privacy(name, rows, config)})",
                "",
            ]

        target = settings.get("target_f1")
        body = []
        for variant in variants:
            fed = {s: r for (v, m, s), r in grouped.items() if v == variant and m == "fedavg"}
            if not fed:
                continue
            central = {s: r[-1]["macro_f1"] for (v, m, s), r in grouped.items() if v == variant and m == "centralised"}
            up = [r[0]["upload_bytes_per_hospital"] / 1e6 for r in fed.values()]
            down = [r[0]["download_bytes_per_hospital"] / 1e6 for r in fed.values()]
            total = [sum(row["upload_bytes_per_hospital"] * row["n_hospitals"] for row in r) / 1e6 for r in fed.values()]
            to_fixed = [rounds_to(r, target) for r in fed.values()]
            to_relative = [rounds_to(r, 0.95 * central[s]) if s in central else None for s, r in fed.items()]
            body.append([variant, fmt(up, 2), fmt(down, 2), fmt(total, 1),
                         fmt_rounds(to_fixed) if target is not None else "-", fmt_rounds(to_relative)])
        lines += [
            "Communication (FedAvg):",
            "",
            table(["Variant", "Upload per hospital per round (MB)", "Download per hospital per round (MB)",
                   "Total upload, all hospitals and rounds (MB)",
                   f"Rounds to macro-F1 ≥ {target}" if target is not None else "Rounds to fixed target",
                   "Rounds to 95% of centralised macro-F1"], body),
            "",
            "Download counts the round's base model and the aggregated model each hospital fetches to evaluate.",
            "",
        ]

    partitions = RESULTS_DIR / name / "partitions.csv"
    if partitions.exists():
        with partitions.open(newline="", encoding="utf-8") as handle:
            prow = list(csv.DictReader(handle))
        excluded = [p for p in prow if p.get("excluded")]
        sizes = [p for p in prow if not p.get("excluded") and p["seed"] == "0"]
        if sizes:
            labels = CLASS_SHORT[modality]
            # Variants that share a partition (e.g. privacy settings) are listed once.
            by_variant: Dict[str, tuple] = defaultdict(tuple)
            for p in sizes:
                by_variant[p["variant"]] += ((p["hospital"], p["train"], p["val"], p["train_labels"]),)
            groups: Dict[tuple, List[str]] = defaultdict(list)
            for variant in variants:
                if variant in by_variant:
                    groups[by_variant[variant]].append(variant)
            body = []
            for partition_rows, names in groups.items():
                label = "all variants" if len(names) == len(by_variant) else ", ".join(names)
                body += [[label, h, t, v] + json.loads(tl) for h, t, v, tl in partition_rows]
            lines += [
                "Partition, seed 0 (training records per class at each hospital):",
                "",
                table(["Variant", "Hospital", "Train", "Held-out"] + [f"train {c}" for c in labels], body),
                "",
            ]
        if modality == "ecg":
            lines += rare_class_table(prow, variants, rare="F")
        if any(p.get("ds1_records") for p in prow):
            lines += records_table(prow)
        if excluded:
            lines += ["Hospitals that sat a run out (too few records to train): "
                      + "; ".join(f"{p['variant']} seed {p['seed']} {p['hospital']} ({p['excluded']})" for p in excluded), ""]
    if settings["dataset"]["source"] == "mitdb":
        lines += beat_check_lines()

    lines += [f"![Learning curves]({figure_curves(name, rows, config, modality)})", ""]
    if len(variants) > 1:
        lines += [f"![Final macro-F1]({figure_bars(name, rows, config)})", ""]
    # No wall-clock times here: runs shared the CPU with other experiments. See the timing table instead.
    return "\n".join(lines)


def rare_class_table(prow: List[dict], variants: List[str], rare: str) -> List[str]:
    """Per-hospital count of a rare class, train / held-out, for every seed and partition."""
    index = CLASS_SHORT["ecg"].index(rare)
    seeds = sorted({p["seed"] for p in prow}, key=int)
    cells: Dict[tuple, Dict[str, str]] = defaultdict(dict)
    for p in prow:
        if p.get("excluded"):
            cells[(p["variant"], p["hospital"])][p["seed"]] = "excluded"
        else:
            train, val = json.loads(p["train_labels"])[index], json.loads(p["val_labels"])[index]
            cells[(p["variant"], p["hospital"])][p["seed"]] = f"{train} / {val}"
    # Variants with identical partitions (e.g. privacy levels) are listed once.
    distinct: Dict[tuple, List[str]] = defaultdict(list)
    for variant in variants:
        key = tuple(sorted((h, tuple(sorted(c.items()))) for (v, h), c in cells.items() if v == variant))
        if key:
            distinct[key].append(variant)
    body = []
    for key, names in distinct.items():
        label = "all variants" if len(names) == len(variants) and len(variants) > 1 else ", ".join(names)
        for hospital, per_seed in key:
            per_seed = dict(per_seed)
            body.append([label, hospital] + [per_seed.get(s, "-") for s in seeds])
    return [
        f"Class {rare} beats per hospital, training / held-out, for each seed (the rarest class; "
        f"its recall rests on these few beats):",
        "",
        table(["Variant", "Hospital"] + [f"seed {s}" for s in seeds], body),
        "",
    ]


def timing_section() -> str:
    """Seconds per round from the separate single-process timing run (``run_experiment.py --time``)."""
    path = RESULTS_DIR / "timing.csv"
    if not path.exists():
        return ""
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    first = rows[0]
    body = [
        [r["experiment"], f"{r['source']} {r['modality'].upper()}", f"{int(r['training_records']):,}",
         METHOD_LABEL[r["method"]], f"{float(r['seconds_per_round']):.1f}"]
        for r in rows
    ]
    return "\n".join(
        [
            "## Run time",
            "",
            "Communication is measured in bytes and in rounds to a target F1 (see each experiment). The experiments "
            "themselves ran three at a time on a shared CPU, so their wall-clock times are not comparable and are not "
            "reported. The table below comes from a separate timing run with one process alone on the machine: "
            f"{first['cpu']}, {first['logical_cpus']} logical CPUs, PyTorch using {first['torch_threads']} threads, "
            f"no GPU. Seed 0, round 1 discarded as warm-up, mean of the next {first['rounds_timed']} rounds. "
            f"A round is {first['local_epochs']} local epochs at every hospital, plus evaluation on the held-out splits; "
            "local-only and centralised train the same amount of data per round as FedAvg.",
            "",
            table(["Experiment", "Data", "Training records", "Method", "Seconds per round"], body),
            "",
        ]
    )


def records_table(prow: List[dict]) -> List[str]:
    """Which PhysioNet records (patients) each hospital held, per seed."""
    body = []
    for p in sorted(prow, key=lambda p: (int(p["seed"]), p["hospital"])):
        if p.get("ds1_records"):
            body.append([p["seed"], p["hospital"], ", ".join(map(str, json.loads(p["ds1_records"]))),
                         ", ".join(map(str, json.loads(p["ds2_records"])))])
    return [
        "Records (patients) per hospital and seed. DS1 records are the hospital's training data, DS2 records its "
        "held-out data; no record appears twice:",
        "",
        table(["Seed", "Hospital", "DS1 records (training)", "DS2 records (held-out)"], body),
        "",
    ]


def beat_check_lines() -> List[str]:
    """The check of extracted PhysioNet beats against the Kaggle export (experiments/check_mitdb_beats.py)."""
    path = RESULTS_DIR / "mitdb_beat_check" / "check.json"
    if not path.exists():
        return []
    check = json.loads(path.read_text())
    body = []
    for c in "NSVF":
        for source, label in (("physionet", "PhysioNet extraction"), ("kaggle", "Kaggle export")):
            s = check[source][c]
            body.append([c, label, f"{s['count']:,}", f"{s['length_median']:.0f} ({s['length_p10']:.0f}-{s['length_p90']:.0f})",
                         f"{s['share_max_is_1']:.3f}", f"{s['share_min_is_0']:.3f}", f"{s['share_peak_at_sample_0']:.3f}"])
    ds = check["ds_counts"]
    return [
        "**Beat check** (`python -m experiments.check_mitdb_beats`, run before any training). Beats are segmented "
        "at the reference R-peak annotations, with no detector, as in de Chazal et al. (2004). Each beat runs from "
        "its R-peak for 1.2 × the median RR interval of its 10 s window, MLII lead at 125 Hz, zero-padded to 187 "
        "samples. Normalisation is per beat (min-max to [0, 1]): the Kaggle export's own data shows this (maximum "
        "exactly 1 and minimum exactly 0 in nearly every beat), although Kachuee et al. (2018) describe normalising "
        f"per 10 s window. Beats extracted: DS1 {', '.join(f'{k} {v:,}' for k, v in ds['DS1'].items())}; "
        f"DS2 {', '.join(f'{k} {v:,}' for k, v in ds['DS2'].items())}; {check['skipped_q']} class-Q beats dropped, "
        f"{check['skipped_other']} beats skipped at record edges or in windows with a single beat.",
        "",
        table(["Class", "Source", "Beats", "Length in samples, median (p10-p90)", "Share max = 1",
               "Share min = 0", "Share peaking at sample 0"], body),
        "",
        "![PhysioNet beats next to Kaggle beats](results/mitdb_beat_check/beats.png)",
        "",
    ]
