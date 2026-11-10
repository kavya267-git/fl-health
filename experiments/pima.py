"""Experiment 1g: EHR baselines on real records (PIMA Indians Diabetes), four hospitals.

    python -m experiments.pima            # run (downloads the data on first use) and write section.md
    python -m experiments.pima --report   # only rewrite section.md from the saved results

Protocol: experiments/configs/pima_ehr_baselines.yaml, fixed before any run.

Through the platform's code where it applies: the Dirichlet split (``partition_groups`` /
``split_train_val``), KNN imputation fitted on each hospital's training split (``ml.ehr.imputation``),
the platform's TabNet network and torch training loop, and for FedAvg the coordinator's
``validate_update`` and ``federated_average``. The PIMA features differ from the platform's 14 EHR
features, so the models are built here with 8 inputs. Local-only and centralised runs, logistic
regression, random forests and gradient boosting are comparison points, not platform features.

Outputs in experiments/results/pima_ehr_baselines/: config.json, dataset.json, partitions.csv,
summary.csv (one row per model, method and seed), reliability.csv, reliability.png and section.md;
predictions.csv (one row per held-out record, model, method and seed) is git-ignored.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "backend"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import torch  # noqa: E402
from torch import nn  # noqa: E402

from app.federated.fedavg import ClientUpdate, federated_average  # noqa: E402
from app.federated.validation import validate_update  # noqa: E402
from ml.common.real_data import partition_groups, split_train_val  # noqa: E402
from ml.common.tasks import EHR_TASK  # noqa: E402
from ml.common.torch_adapter import TorchModelAdapter  # noqa: E402
from ml.common.types import ArrayDataset, TrainConfig  # noqa: E402
from ml.common.weights import weights_from_bytes, weights_to_bytes  # noqa: E402
from ml.ehr.imputation import EHRImputer  # noqa: E402
from ml.ehr.tabnet import TabNet  # noqa: E402

NAME = "pima_ehr_baselines"
CONFIG = ROOT / "experiments" / "configs" / f"{NAME}.yaml"
OUT = ROOT / "experiments" / "results" / NAME
FEATURES = ["preg", "plas", "pres", "skin", "insu", "mass", "pedi", "age"]
FEATURE_LABELS = {
    "preg": "pregnancies",
    "plas": "plasma glucose (2 h OGTT)",
    "pres": "diastolic blood pressure",
    "skin": "triceps skin fold",
    "insu": "2 h serum insulin",
    "mass": "BMI",
    "pedi": "diabetes pedigree function",
    "age": "age",
}
MODEL_LABELS = {
    "tabnet": "TabNet",
    "logistic_regression": "Logistic regression",
    "random_forest": "Random forest",
    "gradient_boosting": "Gradient boosting",
}
METHOD_LABELS = {"local": "Local only", "fedavg": "FedAvg", "centralised": "Centralised"}
MAX_UPDATE_BYTES = 64 * 1024 * 1024


def load_config() -> dict:
    import yaml

    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


# ======================================================================= data
def data_path(config: dict) -> Path:
    override = os.getenv("PIMA_ARFF")
    return Path(override) if override else ROOT / config["dataset"]["path"]


def fetch(config: dict) -> Path:
    """The ARFF file, downloaded once and checked against the published MD5."""
    path = data_path(config)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(config["dataset"]["url"], timeout=60) as response:
            path.write_bytes(response.read())
    digest = hashlib.md5(path.read_bytes()).hexdigest()
    if digest != config["dataset"]["md5"]:
        raise ValueError(f"{path}: MD5 {digest} does not match the published {config['dataset']['md5']}")
    return path


def read_arff(path: Path) -> tuple:
    """Features (zeros kept as zeros) and labels (1 = tested_positive)."""
    text = path.read_text(encoding="utf-8")
    body = text.split("@data", 1)[1] if "@data" in text else text.split("@DATA", 1)[1]
    rows = [r for r in csv.reader(io.StringIO(body)) if r and not r[0].startswith("%")]
    X = np.array([[float(v) for v in r[:8]] for r in rows], dtype=np.float64)
    labels = [r[8].strip() for r in rows]
    if set(labels) != {"tested_negative", "tested_positive"}:
        raise ValueError(f"Unexpected class values: {sorted(set(labels))}")
    y = np.array([1 if v == "tested_positive" else 0 for v in labels], dtype=np.int64)
    return X, y


def mark_missing(X: np.ndarray, config: dict) -> tuple:
    X = X.copy()
    counts = {}
    for name in config["dataset"]["missing_if_zero"]:
        column = FEATURES.index(name)
        zero = X[:, column] == 0
        counts[name] = int(zero.sum())
        X[zero, column] = np.nan
    return X, counts


def make_partition(y: np.ndarray, config: dict) -> Dict[str, dict]:
    spec = config["partition"]
    rng = np.random.default_rng(spec["partition_seed"])
    rows_by_hospital = partition_groups(np.arange(len(y)), y, spec["hospitals"], rng, float(spec["alpha"]))
    out = {}
    for hospital_id in spec["hospitals"]:
        rows = rows_by_hospital.get(hospital_id, np.array([], dtype=np.int64))
        if len(rows) < spec["min_train_records"] + 1:
            out[hospital_id] = {"excluded": f"received {len(rows)} record(s)"}
            continue
        train, val = split_train_val(rows, rng, spec["val_fraction"])
        if len(train) < spec["min_train_records"] or len(val) < 1:
            out[hospital_id] = {"excluded": f"{len(train)} train / {len(val)} held-out records"}
            continue
        out[hospital_id] = {"train": np.sort(rows[train]), "val": np.sort(rows[val])}
    return out


class Preprocessor:
    """What one hospital (or the centralised model) fits on its own training split: KNN imputation + scaling."""

    def __init__(self, X_train: np.ndarray, k: int):
        self.mean = np.nanmean(X_train, axis=0)
        self.std = np.nanstd(X_train, axis=0)
        self.std[self.std == 0] = 1.0
        self.imputer = EHRImputer(n_neighbors=k, scale=(self.mean, self.std)).fit(X_train)

    def __call__(self, X: np.ndarray) -> np.ndarray:
        return ((self.imputer.transform(X) - self.mean) / self.std).astype(np.float32)


# ===================================================================== models
class _PimaAdapter(TorchModelAdapter):
    modality = "ehr"

    def __init__(self):
        super().__init__(EHR_TASK)

    def to_input(self, X: np.ndarray) -> torch.Tensor:
        return torch.from_numpy(np.ascontiguousarray(X, dtype=np.float32))


class PimaTabNetAdapter(_PimaAdapter):
    architecture = "TabNet (PIMA, 8 inputs)"
    summary = "The platform's TabNet with 8 inputs."
    sparsity_weight = 1e-3

    def build_model(self, for_init: bool = False) -> nn.Module:
        return TabNet(len(FEATURES), 2)

    def regulariser(self, model: nn.Module) -> Optional[torch.Tensor]:
        if getattr(model, "last_sparsity_loss", None) is None:
            return None
        return self.sparsity_weight * model.last_sparsity_loss


class _Linear(nn.Module):
    def __init__(self):
        super().__init__()
        self.linear = nn.Linear(len(FEATURES), 2)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.linear(x)


class PimaLogisticAdapter(_PimaAdapter):
    architecture = "Logistic regression (PIMA, 8 inputs)"
    summary = "One linear layer with softmax cross-entropy."

    def build_model(self, for_init: bool = False) -> nn.Module:
        return _Linear()


TORCH_ADAPTERS = {"tabnet": PimaTabNetAdapter, "logistic_regression": PimaLogisticAdapter}


def _dataset(X: np.ndarray, y: np.ndarray, split: str) -> ArrayDataset:
    return ArrayDataset(X, y, "ehr", split, "pima")


def _train_config(training: dict, seed: int) -> TrainConfig:
    return TrainConfig(
        local_epochs=int(training["local_epochs"]),
        batch_size=int(training["batch_size"]),
        learning_rate=float(training["learning_rate"]),
        seed=seed,
        class_weighting=training["class_weighting"],
    )


def _positive(proba: np.ndarray) -> np.ndarray:
    return np.asarray(proba)[:, 1]


def _sklearn_model(model: str, seed: int):
    from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier

    if model == "random_forest":
        return RandomForestClassifier(random_state=seed)
    return GradientBoostingClassifier(random_state=seed)


def _sklearn_positive(fitted, X: np.ndarray) -> np.ndarray:
    """P(positive); a model fitted on one class only predicts that class with certainty."""
    proba = fitted.predict_proba(X)
    classes = list(fitted.classes_)
    if 1 in classes:
        return proba[:, classes.index(1)]
    return np.zeros(len(X))


def run_torch(model: str, method: str, data: Dict[str, dict], training: dict, seed: int) -> Dict[str, np.ndarray]:
    """P(positive) for each hospital's held-out records."""
    adapter = TORCH_ADAPTERS[model]()
    rounds = int(training["rounds"])
    hospitals = list(data)
    if method == "local":
        out = {}
        for index, h in enumerate(hospitals):
            weights = adapter.init_weights(seed)
            train = _dataset(data[h]["X_train"], data[h]["y_train"], "train")
            for r in range(1, rounds + 1):
                weights = adapter.train_local(weights, train, _train_config(training, seed * 100_000 + r * 10 + index)).weights
            out[h] = _positive(adapter.predict_proba(weights, data[h]["X_val"]))
        return out
    if method == "centralised":
        union = _dataset(
            np.concatenate([data[h]["X_train_c"] for h in hospitals]),
            np.concatenate([data[h]["y_train"] for h in hospitals]),
            "train",
        )
        weights = adapter.init_weights(seed)
        for r in range(1, rounds + 1):
            weights = adapter.train_local(weights, union, _train_config(training, seed * 100_000 + r)).weights
        return {h: _positive(adapter.predict_proba(weights, data[h]["X_val_c"])) for h in hospitals}
    # FedAvg: every hospital starts each round from the global weights; the coordinator validates every update
    # and averages them weighted by training records.
    weights = adapter.init_weights(seed)
    signature, label = adapter.signature(), adapter.signature_label
    for r in range(1, rounds + 1):
        updates = []
        for index, h in enumerate(hospitals):
            train = _dataset(data[h]["X_train"], data[h]["y_train"], "train")
            result = adapter.train_local(weights, train, _train_config(training, seed * 100_000 + r * 10 + index))
            payload = weights_to_bytes(result.weights)
            validate_update(payload, result.num_samples, weights, signature, label, signature, MAX_UPDATE_BYTES)
            updates.append(ClientUpdate(h, weights_from_bytes(payload), result.num_samples))
        weights = federated_average(updates)
    return {h: _positive(adapter.predict_proba(weights, data[h]["X_val"])) for h in hospitals}


def run_sklearn(model: str, method: str, data: Dict[str, dict], seed: int) -> Dict[str, np.ndarray]:
    hospitals = list(data)
    if method == "local":
        out = {}
        for h in hospitals:
            fitted = _sklearn_model(model, seed).fit(data[h]["X_train"], data[h]["y_train"])
            out[h] = _sklearn_positive(fitted, data[h]["X_val"])
        return out
    X = np.concatenate([data[h]["X_train_c"] for h in hospitals])
    y = np.concatenate([data[h]["y_train"] for h in hospitals])
    fitted = _sklearn_model(model, seed).fit(X, y)
    return {h: _sklearn_positive(fitted, data[h]["X_val_c"]) for h in hospitals}


# ==================================================================== metrics
def scores(y: np.ndarray, p: np.ndarray, threshold: float) -> dict:
    from sklearn.metrics import brier_score_loss, f1_score, recall_score, roc_auc_score

    predicted = (p >= threshold).astype(int)
    return {
        "roc_auc": float(roc_auc_score(y, p)),
        "f1": float(f1_score(y, predicted, zero_division=0)),
        "recall": float(recall_score(y, predicted, zero_division=0)),
        "brier": float(brier_score_loss(y, p)),
        "predicted_positive_share": float(predicted.mean()),
        "n": int(len(y)),
        "positives": int(y.sum()),
    }


def reliability(y: np.ndarray, p: np.ndarray, bins: int) -> List[dict]:
    edges = np.linspace(0, 1, bins + 1)
    which = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    out = []
    for b in range(bins):
        mask = which == b
        out.append(
            {
                "bin": b,
                "low": float(edges[b]),
                "high": float(edges[b + 1]),
                "n": int(mask.sum()),
                "mean_predicted": float(p[mask].mean()) if mask.any() else None,
                "observed": float(y[mask].mean()) if mask.any() else None,
            }
        )
    return out


# ===================================================================== driver
def prepare(config: dict) -> tuple:
    X_raw, y = read_arff(fetch(config))
    X, zeros = mark_missing(X_raw, config)
    parts = make_partition(y, config)
    k = int(config["preprocessing"]["imputation"]["k"])
    hospitals = [h for h, p in parts.items() if "excluded" not in p]
    data: Dict[str, dict] = {}
    for h in hospitals:
        own = Preprocessor(X[parts[h]["train"]], k)
        data[h] = {
            "X_train": own(X[parts[h]["train"]]),
            "X_val": own(X[parts[h]["val"]]),
            "y_train": y[parts[h]["train"]],
            "y_val": y[parts[h]["val"]],
            "val_rows": parts[h]["val"],
        }
    pooled = Preprocessor(X[np.concatenate([parts[h]["train"] for h in hospitals])], k)
    for h in hospitals:
        data[h]["X_train_c"] = pooled(X[parts[h]["train"]])
        data[h]["X_val_c"] = pooled(X[parts[h]["val"]])
    dataset = {
        "name": config["dataset"]["name"],
        "url": config["dataset"]["url"],
        "md5": config["dataset"]["md5"],
        "records": int(len(y)),
        "positives": int(y.sum()),
        "zeros_treated_as_missing": zeros,
        "rows_with_any_missing": int(np.isnan(X).any(axis=1).sum()),
        "missing_in_held_out": int(sum(np.isnan(X[parts[h]["val"]]).sum() for h in hospitals)),
    }
    partition_rows = []
    for h, p in parts.items():
        if "excluded" in p:
            partition_rows.append({"hospital": h, "excluded": p["excluded"]})
        else:
            partition_rows.append(
                {
                    "hospital": h,
                    "train": len(p["train"]),
                    "train_positive": int(y[p["train"]].sum()),
                    "val": len(p["val"]),
                    "val_positive": int(y[p["val"]].sum()),
                    "missing_values_train": int(np.isnan(X[p["train"]]).sum()),
                    "missing_values_val": int(np.isnan(X[p["val"]]).sum()),
                }
            )
    return data, dataset, partition_rows


def _write_csv(path: Path, rows: List[dict]) -> None:
    columns: List[str] = []
    for row in rows:
        columns.extend(k for k in row if k not in columns)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> List[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def run(config: dict, log=print) -> None:
    import platform

    import sklearn

    OUT.mkdir(parents=True, exist_ok=True)
    data, dataset, partition_rows = prepare(config)
    (OUT / "dataset.json").write_text(json.dumps(dataset, indent=2), encoding="utf-8")
    _write_csv(OUT / "partitions.csv", partition_rows)
    environment = {
        "python": platform.python_version(),
        "torch": torch.__version__,
        "sklearn": sklearn.__version__,
        "numpy": np.__version__,
        "platform": platform.platform(),
        "torch_threads": torch.get_num_threads(),
    }
    (OUT / "config.json").write_text(json.dumps({"config": config, "environment": environment}, indent=2), encoding="utf-8")
    threshold = float(config["metrics"]["threshold"])
    summary, predictions = [], []
    hospitals = list(data)
    for model, methods in config["methods"].items():
        for method in methods:
            for seed in config["seeds"]:
                started = time.perf_counter()
                if config["models"][model]["kind"] == "torch":
                    probs = run_torch(model, method, data, config["training"], seed)
                else:
                    probs = run_sklearn(model, method, data, seed)
                y = np.concatenate([data[h]["y_val"] for h in hospitals])
                p = np.concatenate([probs[h] for h in hospitals])
                row = {"model": model, "method": method, "seed": seed, **scores(y, p, threshold),
                       "seconds": round(time.perf_counter() - started, 1)}
                summary.append(row)
                for h in hospitals:
                    for record, label, prob in zip(data[h]["val_rows"], data[h]["y_val"], probs[h]):
                        predictions.append({"model": model, "method": method, "seed": seed, "hospital": h,
                                            "record": int(record), "label": int(label), "p_positive": float(prob)})
                log(f"[{NAME}] {model} {method} seed {seed}: ROC-AUC {row['roc_auc']:.3f}, F1 {row['f1']:.3f}, "
                    f"recall {row['recall']:.3f}, Brier {row['brier']:.3f} ({row['seconds']} s)")
    _write_csv(OUT / "summary.csv", summary)
    _write_csv(OUT / "predictions.csv", predictions)


def write_reliability(config: dict) -> List[dict]:
    bins = int(config["metrics"]["reliability_bins"])
    predictions = _read_csv(OUT / "predictions.csv")
    groups: Dict[tuple, list] = {}
    for r in predictions:
        groups.setdefault((r["model"], r["method"]), []).append((int(r["label"]), float(r["p_positive"])))
    rows = []
    for (model, method), pairs in groups.items():
        y = np.array([a for a, _ in pairs])
        p = np.array([b for _, b in pairs])
        for b in reliability(y, p, bins):
            rows.append({"model": model, "method": method, **b})
    _write_csv(OUT / "reliability.csv", rows)
    _plot_reliability(rows, config)
    return rows


def _plot_reliability(rows: List[dict], config: dict) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    models = list(config["methods"])
    fig, axes = plt.subplots(1, len(models), figsize=(4 * len(models), 4), sharey=True)
    styles = {"local": ("#9a6324", "s"), "fedavg": ("#24489a", "o"), "centralised": ("#3a8a5c", "^")}
    for ax, model in zip(axes, models):
        ax.plot([0, 1], [0, 1], color="#999999", linewidth=1, linestyle="--", label="perfectly calibrated")
        for method in config["methods"][model]:
            pts = [r for r in rows if r["model"] == model and r["method"] == method and r["n"] and int(r["n"]) >= 5]
            colour, marker = styles[method]
            ax.plot([float(r["mean_predicted"]) for r in pts], [float(r["observed"]) for r in pts],
                    marker=marker, color=colour, linewidth=1.5, markersize=4, label=METHOD_LABELS[method])
        ax.set_title(MODEL_LABELS[model], fontsize=11)
        ax.set_xlabel("Mean predicted probability")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.grid(alpha=0.25)
    axes[0].set_ylabel("Observed share with diabetes")
    axes[0].legend(fontsize=8, loc="upper left")
    fig.suptitle("Reliability on held-out records, 3 seeds pooled (bins with fewer than 5 records left out)", fontsize=11)
    fig.tight_layout()
    fig.savefig(OUT / "reliability.png", dpi=110)
    plt.close(fig)


def _mean_sd(values: List[float]) -> str:
    a = np.array(values, dtype=float)
    return f"{a.mean():.3f} ± {a.std(ddof=1):.3f}" if len(a) > 1 else f"{a.mean():.3f}"


def write_section(config: dict) -> Path:
    summary = _read_csv(OUT / "summary.csv")
    dataset = json.loads((OUT / "dataset.json").read_text(encoding="utf-8"))
    partitions = _read_csv(OUT / "partitions.csv")
    write_reliability(config)
    lines = [f"### {config['title']}", "", config["description"].strip(), ""]
    zeros = ", ".join(f"{FEATURE_LABELS[k]} {v}" for k, v in dataset["zeros_treated_as_missing"].items())
    lines += [
        f"*Config:* `experiments/configs/{NAME}.yaml`. *Run:* `python -m experiments.pima`. "
        f"*Data:* {dataset['name']}, {dataset['records']} records, {dataset['positives']} with diabetes "
        f"({dataset['positives'] / dataset['records']:.0%}). Source: OpenML dataset 37 (the UCI file; original owners "
        "the National Institute of Diabetes and Digestive and Kidney Diseases; donor V. Sigillito, Johns Hopkins "
        "APL; Smith et al., 1988), downloaded from "
        f"<{dataset['url']}> and checked against MD5 `{dataset['md5']}`. Licence: listed by OpenML as \"Public\"; "
        "the file is not redistributed here (git-ignored, downloaded on first run). "
        f"Zeros treated as missing: {zeros}; {dataset['rows_with_any_missing']} records have at least one gap.",
        "",
    ]
    body = []
    for p in partitions:
        if p.get("excluded"):
            body.append([p["hospital"], "excluded: " + p["excluded"], "", "", ""])
        else:
            body.append([p["hospital"], p["train"], f"{int(p['train_positive']) / int(p['train']):.0%}", p["val"],
                         f"{int(p['val_positive']) / int(p['val']):.0%}"])
    lines += ["**Partition** (Dirichlet alpha = 1.0, partition seed 0, the same in every seed):", "",
              "| Hospital | Training records | With diabetes | Held-out records | With diabetes |",
              "| --- | --- | --- | --- | --- |"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in body]
    held = [p for p in partitions if not p.get("excluded")]
    n_val = sum(int(p["val"]) for p in held)
    pos_val = sum(int(p["val_positive"]) for p in held)
    lines += ["", f"Scores below are on the {n_val} held-out records of all hospitals pooled ({pos_val} with diabetes), "
              "mean ± SD over 3 seeds. With so few held-out records, a difference of a few hundredths in ROC-AUC "
              "is within what a different split could change; the SD shows only seed-to-seed variation, not "
              "this sampling uncertainty.", ""]
    lines += ["| Model | Method | ROC-AUC | F1 | Recall (sensitivity) | Brier score (lower is better) |",
              "| --- | --- | --- | --- | --- | --- |"]
    for model, methods in config["methods"].items():
        for method in methods:
            rows = [r for r in summary if r["model"] == model and r["method"] == method]
            if not rows:
                continue
            lines.append("| " + " | ".join([
                MODEL_LABELS[model], METHOD_LABELS[method],
                _mean_sd([float(r["roc_auc"]) for r in rows]), _mean_sd([float(r["f1"]) for r in rows]),
                _mean_sd([float(r["recall"]) for r in rows]), _mean_sd([float(r["brier"]) for r in rows]),
            ]) + " |")
    lines += [
        "",
        "Local only: each hospital's own model, scored on its own held-out records. FedAvg: the final global "
        "model (30 rounds), scored on every hospital's held-out records with that hospital's own preprocessing. "
        "Centralised: one model trained on the union of the training splits (preprocessing fitted on the union), "
        "an upper bound that the platform does not offer. FedAvg is shown only for TabNet and logistic "
        "regression, whose parameters can be averaged. F1 and recall use the 0.5 threshold; the threshold was "
        "not tuned.",
        "",
        f"![Reliability plot](results/{NAME}/reliability.png)",
        "",
        "Calibration data per bin: `experiments/results/pima_ehr_baselines/reliability.csv`.",
        "",
    ]
    path = OUT / "section.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report", action="store_true", help="Only rewrite section.md from saved results")
    args = parser.parse_args()
    config = load_config()
    if not args.report:
        run(config)
    print(f"Wrote {write_section(config)}")


if __name__ == "__main__":
    main()
