"""Reproducible federated-learning experiments for the project report.

Rounds run in-process for speed, but through the platform's own code paths:

* each hospital is a ``ml.training.hospital_node.HospitalNode`` reading its own
  partition from disk; local training, the DP mechanism and local evaluation
  are the node's code;
* every update passes the coordinator's ``validate_update`` and is aggregated
  with the coordinator's ``federated_average``;
* privacy is accounted with ``analytics.privacy.dp.account_rounds``, the
  function behind the platform's privacy page;
* real data is partitioned with ``partition_groups`` / ``split_train_val`` from
  ``ml.common.real_data``, the functions ``scripts/prepare_real_data.py`` uses.

Only the transport differs: an in-memory object with the same contract as
``LocalTransport`` / ``HttpTransport``, which also counts the bytes moved.

Two comparison points are *not* part of the platform and exist only here:
each hospital training alone ("local"), and a model trained offline on the
union of the hospitals' training partitions ("centralised", an upper bound).

Every metric is computed from the confusion matrices of each hospital's
held-out split, pooled across hospitals. The held-out split is never used for
training, early stopping or choosing hyperparameters: all settings come from
the config file, fixed before a run.
"""

from __future__ import annotations

import copy
import csv
import json
import math
import os
import platform
import shutil
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "backend"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

os.environ.setdefault("ML_BACKEND", "pytorch")

if os.getenv("FL_EXPERIMENT_THREADS"):
    # Lets several experiments share a machine without oversubscribing it. Recorded in config.json.
    import torch

    torch.set_num_threads(int(os.environ["FL_EXPERIMENT_THREADS"]))

from analytics.privacy.dp import DPConfig, account_rounds, is_statistic, next_clip_norm, update_norm  # noqa: E402
from app.federated.fedavg import ClientUpdate, federated_average  # noqa: E402
from app.federated.validation import UpdateRejected, validate_update  # noqa: E402
from ml import __version__  # noqa: E402
from ml.common.datasets import load_local_dataset, save_local_dataset  # noqa: E402
from ml.common.real_data import DEFAULT_HOSPITALS, partition_groups, split_train_val  # noqa: E402
from ml.common.types import ArrayDataset, EvalResult, TrainConfig  # noqa: E402
from ml.common.weights import weights_from_bytes, weights_to_bytes  # noqa: E402
from ml.ecg.preprocess import ECG_BEAT_LENGTH  # noqa: E402
from ml.ehr.imputation import MissingnessConfig  # noqa: E402
from ml.evaluation.metrics import per_class_metrics, pool_evaluations  # noqa: E402
from ml.registry import adapter_override, get_adapter  # noqa: E402
from ml.simulation.hospitals import SIMULATED_HOSPITALS, generate_hospital_data  # noqa: E402
from ml.training.hospital_node import HospitalNode  # noqa: E402
from ml.training.local_trainer import load_training_splits  # noqa: E402

RESULTS_DIR = ROOT / "experiments" / "results"
WORK_DIR = ROOT / "experiments" / ".work"
MAX_UPDATE_BYTES = 256 * 1024 * 1024
METHODS = ("local", "fedavg", "centralised")
#: Short, column-safe class labels per modality, in task order.
CLASS_SHORT = {"ecg": ("N", "S", "V", "F"), "ehr": ("neg", "pos"), "xray": ("no_finding", "finding")}
#: Hospitals with fewer training records than this cannot train (batch norm needs 2) and sit the run out.
MIN_TRAIN_RECORDS = 8

DEFAULTS = {
    "description": "",
    "dataset": {"modality": "ecg", "source": "simulated", "csv": [], "scale": 1.0, "max_records": None},
    "partition": {"scheme": "natural", "alpha": None, "val_fraction": 0.25},
    "training": {
        "rounds": 20,
        "local_epochs": 2,
        "batch_size": 32,
        "learning_rate": 0.003,
        "class_weighting": "none",
        "proximal_mu": 0.0,
        # EHR only: {"mcar_rate": r, "seed": s} blanks a share of feature values at random; each hospital
        # fills them by KNN imputation fitted on its own training split (ml.ehr.imputation).
        "missingness": None,
    },
    # adaptive_clipping / target_quantile / clip_learning_rate / quantile_budget_share: see analytics.privacy.dp.
    "dp": {"enabled": False, "clip_norm": 1.0, "noise_multiplier": 0.0, "delta": 1e-5},
    "methods": ["local", "fedavg", "centralised"],
    "seeds": [0, 1, 2],
    "target_f1": None,
    "variants": [{"label": "default"}],
    # Diagnostics only (experiment harness, never the platform):
    # name used in FedAvg round ids, which seed each hospital's data order; None = the experiment's name.
    "round_id_name": None,
    # {"clip_norm": C, "bn_statistics": "local" | "global"}: clip each update to C with no noise.
    "diagnostic_clip": None,
}


# ===================================================================== config
def deep_merge(base: dict, override: dict) -> dict:
    merged = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _alpha(value) -> Optional[float]:
    """None means an even random split (alpha = infinity)."""
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() in ("inf", "infinity", ".inf", "iid"):
        return None
    value = float(value)
    return None if math.isinf(value) else value


def load_config(path: Path) -> dict:
    text = Path(path).read_text(encoding="utf-8")
    if Path(path).suffix.lower() in (".yaml", ".yml"):
        import yaml

        raw = yaml.safe_load(text)
    else:
        raw = json.loads(text)
    config = deep_merge(DEFAULTS, raw)
    config.setdefault("name", Path(path).stem)
    config["dataset"]["csv"] = [os.path.expandvars(str(p)) for p in config["dataset"].get("csv") or []]
    for method in config["methods"]:
        if method not in METHODS:
            raise ValueError(f"Unknown method '{method}'. Use {METHODS}")
    labels = [v.get("label") for v in config["variants"]]
    if len(set(labels)) != len(labels) or None in labels:
        raise ValueError("Every variant needs a unique 'label'")
    return config


def variant_config(config: dict, variant: dict) -> dict:
    """The full settings of one variant (its overrides applied to the base config)."""
    overrides = {k: v for k, v in variant.items() if k not in ("label", "methods")}
    resolved = deep_merge(config, overrides)
    resolved["methods"] = variant.get("methods", config["methods"])
    return resolved


# ======================================================================= data
@dataclass
class Partition:
    root: Path
    modality: str
    source: str
    hospitals: List[str]
    excluded: Dict[str, str] = field(default_factory=dict)
    sizes: Dict[str, dict] = field(default_factory=dict)
    records: Dict[str, dict] = field(default_factory=dict)  # patient-wise setting: records per hospital
    missingness: Optional[dict] = None

    def load(self, hospital_id: str, split: str) -> ArrayDataset:
        """What the hospital node trains / evaluates on: for EHR, gaps filled from its own training split."""
        if self.modality != "ehr":
            return load_local_dataset(self.root / hospital_id, self.modality, split)
        train, val, _ = load_training_splits(
            self.root / hospital_id, self.modality, MissingnessConfig.from_dict(self.missingness)
        )
        return train if split == "train" else val


def load_mitbih(csv_paths: Iterable[str]) -> tuple:
    """The MIT-BIH heartbeat export, read exactly as ``prepare_ecg_heartbeat_csv`` reads it (class Q dropped)."""
    import pandas as pd

    paths = [Path(p) for p in csv_paths]
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        raise FileNotFoundError(f"MIT-BIH CSV not found: {missing}. Set the paths in the config (or MITBIH_DIR).")
    table = pd.concat([pd.read_csv(p, header=None) for p in paths], ignore_index=True)
    if table.shape[1] != ECG_BEAT_LENGTH + 1:
        raise ValueError(f"Expected {ECG_BEAT_LENGTH + 1} columns, got {table.shape[1]}")
    labels = table.iloc[:, -1].to_numpy().astype(np.int64)
    keep = labels <= 3
    return table.iloc[:, :-1].to_numpy(dtype=np.float32)[keep], labels[keep]


_POOL_CACHE: Dict[tuple, tuple] = {}
#: Description of the last real-data pool (records available / used per class), written to dataset.json.
POOL_SUMMARY: Dict[str, object] = {}


def _pooled_records(dataset: dict, seed: int, work_root: Path) -> tuple:
    """All records available to the federation, before they are split between hospitals."""
    modality, source = dataset["modality"], dataset["source"]
    if source == "simulated":
        root = work_root / "simulated-pool" / f"{modality}-seed{seed}-scale{dataset['scale']}"
        X_parts, y_parts = [], []
        for hospital in SIMULATED_HOSPITALS:
            generate_hospital_data(root, hospital, seed=2024 + seed, modalities=[modality], scale=dataset["scale"])
            for split in ("train", "val"):
                part = load_local_dataset(root / hospital.hospital_id, modality, split)
                X_parts.append(part.X)
                y_parts.append(part.y)
        return np.concatenate(X_parts), np.concatenate(y_parts)
    if source == "mit-bih":
        if modality != "ecg":
            raise ValueError("The MIT-BIH heartbeat export is an ECG dataset")
        key = tuple(dataset["csv"])
        if key not in _POOL_CACHE:
            _POOL_CACHE[key] = load_mitbih(dataset["csv"])
        X, y = _POOL_CACHE[key]
        available = np.bincount(y, minlength=len(CLASS_SHORT["ecg"])).tolist()
        limit = dataset.get("max_records")
        if limit and limit < len(y):
            # Stratified subsample to bound run time, drawn ONCE with subsample_seed: the same records
            # for every seed and every experiment that names the same files. Disclosed in the results.
            rng = np.random.default_rng(int(dataset.get("subsample_seed", 0)))
            keep = []
            for label in np.unique(y):
                rows = np.where(y == label)[0]
                take = max(1, int(round(len(rows) * limit / len(y))))
                keep.append(rng.choice(rows, size=min(take, len(rows)), replace=False))
            keep = np.sort(np.concatenate(keep))
            X, y = X[keep], y[keep]
        POOL_SUMMARY.clear()
        POOL_SUMMARY.update(
            {
                "files": [Path(p).name for p in dataset["csv"]],
                "classes": list(CLASS_SHORT["ecg"]),
                "records_available": int(sum(available)),
                "class_counts_available": available,
                "records_used": int(len(y)),
                "class_counts_used": np.bincount(y, minlength=len(available)).tolist(),
                "subsample": (
                    {"method": "stratified by class, without replacement", "max_records": limit,
                     "subsample_seed": int(dataset.get("subsample_seed", 0))}
                    if limit and limit < sum(available) else None
                ),
            }
        )
        return X, y
    raise ValueError(f"Unknown dataset source '{source}' for a Dirichlet split. Use 'simulated' or 'mit-bih'.")


def build_partition(config: dict, seed: int, run_dir: Path) -> Partition:
    """Write each hospital's train / held-out split for this run under ``run_dir``."""
    dataset, scheme = config["dataset"], config["partition"]
    modality, source = dataset["modality"], dataset["source"]
    if run_dir.exists():
        shutil.rmtree(run_dir)
    hospitals = list(DEFAULT_HOSPITALS)
    partition = Partition(run_dir, modality, source, [], missingness=config["training"].get("missingness"))

    if scheme["scheme"] == "natural":
        if source != "simulated":
            raise ValueError("The 'natural' partition exists only for simulated hospitals; use 'dirichlet'")
        for hospital in SIMULATED_HOSPITALS:
            generate_hospital_data(run_dir, hospital, seed=2024 + seed, modalities=[modality], scale=dataset["scale"])
    elif scheme["scheme"] == "dirichlet":
        X, y = _pooled_records(dataset, seed, run_dir.parent)
        rng = np.random.default_rng(seed)
        rows_by_hospital = partition_groups(np.arange(len(y)), y, hospitals, rng, _alpha(scheme["alpha"]))
        for hospital_id, rows in rows_by_hospital.items():
            if len(rows) < MIN_TRAIN_RECORDS + 1:
                partition.excluded[hospital_id] = f"received {len(rows)} record(s)"
                continue
            train, val = split_train_val(rows, rng, scheme["val_fraction"])
            if len(train) < MIN_TRAIN_RECORDS or len(val) < 1:
                partition.excluded[hospital_id] = f"{len(train)} train / {len(val)} held-out records"
                continue
            label = "simulated" if source == "simulated" else source
            save_local_dataset(
                run_dir / hospital_id,
                modality,
                train=(X[rows[train]], y[rows[train]]),
                val=(X[rows[val]], y[rows[val]]),
                source=label,
                description=f"experiment partition, Dirichlet alpha={scheme['alpha']}, seed {seed}",
            )
    elif scheme["scheme"] == "records":
        # Patient-wise: whole PhysioNet records dealt to hospitals, DS1 for training, DS2 held out.
        from experiments import mitdb

        if source != "mitdb":
            raise ValueError("The 'records' partition needs dataset.source 'mitdb'")
        beats = mitdb.load_all(Path(dataset["mitdb_dir"]), WORK_DIR / "mitdb-beats.npz")
        if dataset.get("rr_features"):
            # Experiment 1f: the same beats, each row followed by its pre-RR, post-RR and local average RR.
            rr = mitdb.load_rr(Path(dataset["mitdb_dir"]), WORK_DIR / "mitdb-rr.npz")
            beats = {r: (np.concatenate([X, rr[r]], axis=1), y) for r, (X, y) in beats.items()}
        for hospital_id, records in mitdb.assign_records(seed, hospitals).items():
            train = [beats[r] for r in records["ds1"]]
            val = [beats[r] for r in records["ds2"]]
            save_local_dataset(
                run_dir / hospital_id,
                modality,
                train=(np.concatenate([b[0] for b in train]), np.concatenate([b[1] for b in train])),
                val=(np.concatenate([b[0] for b in val]), np.concatenate([b[1] for b in val])),
                source="mitdb",
                description=f"PhysioNet MIT-BIH, DS1 records {records['ds1']}, DS2 records {records['ds2']}",
            )
            partition.records[hospital_id] = records
    else:
        raise ValueError("partition.scheme must be 'natural', 'dirichlet' or 'records'")

    k = len(CLASS_SHORT[modality])
    for hospital_id in hospitals:
        if hospital_id in partition.excluded:
            continue
        train, val = partition.load(hospital_id, "train"), partition.load(hospital_id, "val")
        if len(train) < MIN_TRAIN_RECORDS:
            partition.excluded[hospital_id] = f"{len(train)} train records"
            continue
        partition.hospitals.append(hospital_id)
        partition.sizes[hospital_id] = {
            "train": len(train),
            "val": len(val),
            "train_labels": np.bincount(train.y, minlength=k).tolist(),
            "val_labels": np.bincount(val.y, minlength=k).tolist(),
        }
        if hospital_id in partition.records:
            partition.sizes[hospital_id]["ds1_records"] = partition.records[hospital_id]["ds1"]
            partition.sizes[hospital_id]["ds2_records"] = partition.records[hospital_id]["ds2"]
    if len(partition.hospitals) < 2:
        raise ValueError(f"Fewer than two hospitals can train in this partition: {partition.excluded}")
    return partition


# ==================================================================== metrics
def metric_row(confusion: np.ndarray, modality: str, loss_sum: float, n: int) -> dict:
    adapter = get_adapter(modality)
    per_class = per_class_metrics(np.asarray(confusion), adapter.task.class_names)
    row = {
        "accuracy": float(np.trace(confusion) / max(np.sum(confusion), 1)),
        "macro_f1": float(np.mean([c["f1"] for c in per_class])),
        "macro_recall": float(np.mean([c["recall"] for c in per_class])),
        "loss": loss_sum / max(n, 1),
        "n_eval": int(n),
    }
    predicted = np.asarray(confusion).sum(axis=0) / max(np.sum(confusion), 1)  # rows true, columns predicted
    for short, metrics, share in zip(CLASS_SHORT[modality], per_class, predicted):
        row[f"recall_{short}"] = metrics["recall"]  # sensitivity, Se
        row[f"precision_{short}"] = metrics["precision"]  # positive predictivity, +P
        row[f"predicted_{short}"] = float(share)  # share of held-out beats predicted as this class
    row["confusion"] = json.dumps(np.asarray(confusion).astype(int).tolist())
    if adapter.task.task_type == "binary":
        row["f1_pos"] = per_class[1]["f1"]
        row["precision_pos"] = per_class[1]["precision"]
    return row


def pooled_row(results: List[EvalResult], modality: str) -> dict:
    pooled = pool_evaluations(results)
    return metric_row(pooled.confusion, modality, pooled.loss_sum, pooled.num_samples)


# ================================================================== transport
class InMemoryTransport:
    """Same contract as LocalTransport / HttpTransport; records what crosses the boundary."""

    def __init__(self):
        self.round_info: dict = {}
        self.base = b""
        self.result = b""
        self.updates: Dict[str, dict] = {}
        self.evaluations: Dict[str, EvalResult] = {}
        self.failures: Dict[str, str] = {}
        self.downloaded: Dict[str, int] = defaultdict(int)

    def join_round(self, round_id, hospital_id, data_summary):
        return self.round_info

    def fetch_global_model(self, round_id, hospital_id, which):
        payload = self.base if which == "base" else self.result
        self.downloaded[hospital_id] += len(payload)
        return payload

    def submit_update(self, round_id, hospital_id, payload, num_samples, metrics, dp_report, architecture_signature):
        self.updates[hospital_id] = {
            "payload": payload,
            "num_samples": num_samples,
            "metrics": metrics,
            "dp_report": dp_report,
            "signature": architecture_signature,
        }
        return {"status": "RECEIVED"}

    def submit_evaluation(self, round_id, hospital_id, evaluation, explanation):
        self.evaluations[hospital_id] = EvalResult.from_dict(evaluation)
        return {"status": "RECORDED"}

    def report_failure(self, round_id, hospital_id, stage, message):
        self.failures[hospital_id] = f"{stage}: {message}"


# ==================================================================== methods
def diagnostic_clip(global_weights: dict, local_weights: dict, clip_norm: float, bn_statistics: str) -> tuple:
    """Clip one update to ``clip_norm`` without noise. A diagnostic for the harness only.

    Same scaling as ``analytics.privacy.dp.privatize_update`` with the noise left out (the platform refuses
    DP without noise). ``bn_statistics`` says what the hospital sends for batch-norm running statistics:
    "local" its own, as the platform's DP does; "global" the round's global values, unchanged.
    """
    if bn_statistics not in ("local", "global"):
        raise ValueError("diagnostic_clip.bn_statistics must be 'local' or 'global'")
    norm = update_norm(global_weights, local_weights)
    scale = min(1.0, clip_norm / norm) if norm > 0 else 1.0
    out = {}
    for key, local in local_weights.items():
        local = np.asarray(local)
        if is_statistic(key):
            out[key] = (np.asarray(global_weights[key]) if bn_statistics == "global" else local).copy()
        elif np.issubdtype(local.dtype, np.floating):
            base = np.asarray(global_weights[key], dtype=np.float64)
            out[key] = (base + (local.astype(np.float64) - base) * scale).astype(local.dtype)
        else:
            out[key] = local.copy()
    return out, scale < 1.0


def _train_config(training: dict, seed: int) -> TrainConfig:
    return TrainConfig(
        local_epochs=int(training["local_epochs"]),
        batch_size=int(training["batch_size"]),
        learning_rate=float(training["learning_rate"]),
        seed=seed,
        class_weighting=training["class_weighting"],
        proximal_mu=float(training["proximal_mu"]),
    )


def run_fedavg(config: dict, partition: Partition, seed: int) -> List[dict]:
    """Federated rounds through the platform's node, validation, FedAvg and DP accounting."""
    modality, training = partition.modality, config["training"]
    adapter = get_adapter(modality)
    weights = adapter.init_weights(seed)
    signature, label = adapter.signature(), adapter.signature_label
    transport = InMemoryTransport()
    nodes = {h: HospitalNode(h, partition.root / h, transport) for h in partition.hospitals}
    dp = DPConfig.from_dict(config["dp"])
    dp_reports: Dict[str, List[dict]] = defaultdict(list)
    rows = []
    for round_number in range(1, int(training["rounds"]) + 1):
        started = time.perf_counter()
        clip_this_round = dp.clip_norm
        round_id = f"{config.get('round_id_name') or config['name']}-seed{seed}-r{round_number:03d}"
        transport.base = weights_to_bytes(weights)
        transport.updates, transport.evaluations, transport.failures = {}, {}, {}
        transport.downloaded.clear()
        transport.round_info = {
            "round_id": round_id,
            "modality": modality,
            "status": "TRAINING",
            "training": {
                "local_epochs": training["local_epochs"],
                "batch_size": training["batch_size"],
                "learning_rate": training["learning_rate"],
                "seed": seed * 100_000 + round_number,
                "class_weighting": training["class_weighting"],
                "proximal_mu": training["proximal_mu"],
                **({"missingness": training["missingness"]} if training.get("missingness") else {}),
            },
            "differential_privacy": dp.to_dict(),
            "model": {"architecture": adapter.architecture, "backend": adapter.backend},
            "explainability": {"global_importance": False},
        }
        for node in nodes.values():
            node.train_and_submit(round_id, transport.round_info)
        clip = config.get("diagnostic_clip")
        if clip:
            # Applied as each update arrives, before validation: nothing touches it in between, so this is
            # the same as clipping at the hospital.
            for update in transport.updates.values():
                clipped, was_clipped = diagnostic_clip(
                    weights, weights_from_bytes(update["payload"]), float(clip["clip_norm"]), clip["bn_statistics"]
                )
                update["payload"] = weights_to_bytes(clipped)
                update["dp_report"] = {**update["dp_report"], "clipped": was_clipped}

        accepted, rejected = [], {}
        for hospital_id, update in transport.updates.items():
            try:
                validate_update(
                    update["payload"],
                    update["num_samples"],
                    weights,
                    signature,
                    label,
                    update["signature"],
                    MAX_UPDATE_BYTES,
                )
            except UpdateRejected as exc:
                rejected[hospital_id] = exc.reason
                continue
            accepted.append(
                ClientUpdate(hospital_id, weights_from_bytes(update["payload"]), int(update["num_samples"]))
            )
            dp_reports[hospital_id].append(update["dp_report"])
        if len(accepted) < 2:
            raise RuntimeError(f"Round {round_id}: only {len(accepted)} valid update(s); rejected {rejected}")
        weights = federated_average(accepted)
        transport.result = weights_to_bytes(weights)
        clip_step = None
        if dp.enabled and dp.adaptive_clipping:
            # As the coordinator does after aggregation: the next clip norm from the accepted updates' noised bits.
            clip_step = next_clip_norm(
                dp.clip_norm,
                [transport.updates[u.hospital_id]["dp_report"]["noisy_clip_bit"] for u in accepted],
                dp.target_quantile,
                dp.clip_learning_rate,
            )
            dp = replace(dp, clip_norm=clip_step["clip_norm"])
        for hospital_id, node in nodes.items():
            if hospital_id in {u.hospital_id for u in accepted}:
                node.evaluate_and_report(round_id, transport.round_info)

        uploads = [len(u["payload"]) for u in transport.updates.values()]
        # With DP the reports withhold the raw norm and the clipped flag; the harness reads the nodes' local
        # diagnostic instead (never sent), so the experiment logs keep the same columns.
        norms = [nodes[h].last_update_norm for h in transport.updates]
        clipped = [
            u["dp_report"]["clipped"] if u["dp_report"].get("clipped") is not None
            else bool(u["dp_report"].get("clip_norm") and nodes[h].last_update_norm > u["dp_report"]["clip_norm"])
            for h, u in transport.updates.items()
        ]
        accounting = account_rounds(dp_reports[accepted[0].hospital_id], dp.delta)
        epsilon = accounting["epsilon_over_dp_rounds"]
        row = pooled_row(list(transport.evaluations.values()), modality)
        row.update(
            round=round_number,
            n_hospitals=len(accepted),
            upload_bytes_per_hospital=float(np.mean(uploads)),
            download_bytes_per_hospital=float(np.mean(list(transport.downloaded.values()))),
            median_update_norm=float(np.median(norms)) if norms else None,
            clipped_share=float(np.mean(clipped)) if clipped else None,
            epsilon=math.inf if epsilon is None else float(epsilon),
            clip_norm=float(clip_this_round) if dp.enabled else None,
            estimated_share_unclipped=clip_step["estimated_share_unclipped"] if clip_step else None,
            rejected=len(rejected),
            seconds=time.perf_counter() - started,
        )
        rows.append(row)
    return rows


def run_local(config: dict, partition: Partition, seed: int) -> List[dict]:
    """Each hospital trains alone for the same number of rounds x local epochs. Not part of the platform."""
    modality, training = partition.modality, config["training"]
    adapter = get_adapter(modality)
    models = {h: adapter.init_weights(seed) for h in partition.hospitals}
    rows = []
    for round_number in range(1, int(training["rounds"]) + 1):
        started = time.perf_counter()
        own = []
        for index, hospital_id in enumerate(partition.hospitals):
            cfg = _train_config(training, seed * 100_000 + round_number * 10 + index)
            models[hospital_id] = adapter.train_local(models[hospital_id], partition.load(hospital_id, "train"), cfg).weights
            own.append(adapter.evaluate(models[hospital_id], partition.load(hospital_id, "val")))
        row = pooled_row(own, modality)
        row.update(round=round_number, n_hospitals=len(partition.hospitals), seconds=time.perf_counter() - started)
        rows.append(row)
    # Final local models on every hospital's held-out split: does a hospital's model generalise to the others?
    cross = [
        adapter.evaluate(models[model_of], partition.load(split_of, "val"))
        for model_of in partition.hospitals
        for split_of in partition.hospitals
    ]
    # Every metric, prefixed "cross_": each hospital's model on all hospitals' held-out data, pooled.
    rows[-1].update({f"cross_{key}": value for key, value in pooled_row(cross, modality).items()})
    return rows


def run_centralised(config: dict, partition: Partition, seed: int) -> List[dict]:
    """Upper bound: one model trained offline on the union of the training partitions. Not part of the platform."""
    modality, training = partition.modality, config["training"]
    adapter = get_adapter(modality)
    trains = [partition.load(h, "train") for h in partition.hospitals]
    union = ArrayDataset(
        np.concatenate([t.X for t in trains]), np.concatenate([t.y for t in trains]), modality, "train", "union"
    )
    vals = [partition.load(h, "val") for h in partition.hospitals]
    weights = adapter.init_weights(seed)
    rows = []
    for round_number in range(1, int(training["rounds"]) + 1):
        started = time.perf_counter()
        weights = adapter.train_local(weights, union, _train_config(training, seed * 100_000 + round_number)).weights
        row = pooled_row([adapter.evaluate(weights, v) for v in vals], modality)
        row.update(round=round_number, n_hospitals=len(partition.hospitals), seconds=time.perf_counter() - started)
        rows.append(row)
    return rows


RUNNERS = {"local": run_local, "fedavg": run_fedavg, "centralised": run_centralised}


def run_method(method: str, settings: dict, partition: Partition, seed: int) -> List[dict]:
    """Run one method, with the model named in ``settings["model"]`` if it is not the platform's default."""
    architecture = (settings.get("model") or {}).get("architecture")
    if not architecture:
        return RUNNERS[method](settings, partition, seed)
    if architecture != "CNN-BiLSTM+RR" or partition.modality != "ecg":
        raise ValueError(f"Unknown experiment model '{architecture}' for {partition.modality}")
    from ml.ecg.cnn_bilstm import CNNBiLSTMRRAdapter

    with adapter_override("ecg", CNNBiLSTMRRAdapter()):
        return RUNNERS[method](settings, partition, seed)


# ===================================================================== driver
def environment() -> dict:
    import torch

    return {
        "fl_healthcare": __version__,
        "python": platform.python_version(),
        "torch": torch.__version__,
        "numpy": np.__version__,
        "platform": platform.platform(),
        "cpu_threads": torch.get_num_threads(),
    }


def _read_rows(path: Path) -> List[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_rows(path: Path, rows: List[dict]) -> None:
    columns: List[str] = []
    for row in rows:
        columns.extend(k for k in row if k not in columns)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def run_experiment(config: dict, resume: bool = True, log=print) -> Path:
    """Run every variant x seed x method; write CSVs incrementally so a long run can resume."""
    out = RESULTS_DIR / config["name"]
    out.mkdir(parents=True, exist_ok=True)
    rounds_path, partitions_path = out / "rounds.csv", out / "partitions.csv"
    rows = _read_rows(rounds_path) if resume else []
    partition_rows = _read_rows(partitions_path) if resume else []
    done = {(r["variant"], r["seed"], r["method"]) for r in rows}
    (out / "config.json").write_text(json.dumps({"config": config, "environment": environment()}, indent=2, default=str))

    for variant in config["variants"]:
        settings = variant_config(config, variant)
        for seed in settings["seeds"]:
            pending = [m for m in settings["methods"] if (variant["label"], str(seed), m) not in done]
            if not pending:
                continue
            partition = build_partition(settings, seed, WORK_DIR / config["name"] / f"{variant['label']}-seed{seed}")
            if POOL_SUMMARY:
                (out / "dataset.json").write_text(json.dumps(POOL_SUMMARY, indent=2))
            if not any(p["variant"] == variant["label"] and p["seed"] == str(seed) for p in partition_rows):
                for hospital_id, size in partition.sizes.items():
                    partition_rows.append(
                        {"variant": variant["label"], "seed": str(seed), "hospital": hospital_id, **{
                            k: json.dumps(v) if isinstance(v, list) else v for k, v in size.items()
                        }}
                    )
                for hospital_id, reason in partition.excluded.items():
                    partition_rows.append(
                        {"variant": variant["label"], "seed": str(seed), "hospital": hospital_id, "excluded": reason}
                    )
                _write_rows(partitions_path, partition_rows)
            for method in pending:
                started = time.perf_counter()
                result = run_method(method, settings, partition, seed)
                for row in result:
                    rows.append(
                        {
                            "experiment": config["name"],
                            "variant": variant["label"],
                            "method": method,
                            "seed": str(seed),
                            "modality": partition.modality,
                            "source": partition.source,
                            **row,
                        }
                    )
                _write_rows(rounds_path, rows)
                final = result[-1]
                log(
                    f"[{config['name']}] {variant['label']} seed {seed} {method}: "
                    f"macro-F1 {final['macro_f1']:.3f}, accuracy {final['accuracy']:.3f} "
                    f"({time.perf_counter() - started:.0f} s)"
                )
            shutil.rmtree(partition.root, ignore_errors=True)
    return out


# ===================================================================== timing
def cpu_name() -> str:
    try:
        import winreg

        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
        return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
    except (ImportError, OSError):
        pass
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "unknown"


def time_methods(config: dict, rounds: int = 3, log=print) -> List[dict]:
    """Seconds per round of each method, measured alone on the machine.

    Seed 0 and the config's first variant; round 1 is discarded as warm-up and
    the remaining rounds are averaged. Meant to be run when nothing else is
    using the CPU, unlike the experiments themselves, which may share it.
    """
    import torch

    settings = deep_merge(variant_config(config, config["variants"][0]), {"training": {"rounds": rounds}})
    partition = build_partition(settings, 0, WORK_DIR / "timing" / config["name"])
    records = sum(s["train"] for s in partition.sizes.values())
    out = []
    for method in settings["methods"]:
        result = run_method(method, settings, partition, 0)
        timed = [row["seconds"] for row in result[1:]]
        out.append(
            {
                "experiment": config["name"],
                "modality": partition.modality,
                "source": partition.source,
                "training_records": records,
                "hospitals": len(partition.hospitals),
                "local_epochs": settings["training"]["local_epochs"],
                "method": method,
                "seconds_per_round": float(np.mean(timed)),
                "rounds_timed": len(timed),
                "cpu": cpu_name(),
                "logical_cpus": os.cpu_count(),
                "torch_threads": torch.get_num_threads(),
            }
        )
        log(f"[timing] {config['name']} {method}: {out[-1]['seconds_per_round']:.1f} s per round")
    shutil.rmtree(partition.root, ignore_errors=True)
    return out
