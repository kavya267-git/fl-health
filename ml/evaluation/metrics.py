"""Classification metrics computed from pooled confusion matrices."""

from __future__ import annotations

from typing import Dict, Iterable, List

import numpy as np

from ml.common.types import EvalResult, TaskSpec

METRIC_DEFINITIONS_BINARY = {
    "accuracy": "Share of evaluation records classified correctly.",
    "precision": "Of the records predicted positive, the share that were truly positive.",
    "recall": "Of the truly positive records, the share the model found (sensitivity).",
    "f1": "Harmonic mean of precision and recall for the positive class.",
    "loss": "Mean cross-entropy on the evaluation split (lower is better).",
}

METRIC_DEFINITIONS_MULTICLASS = {
    "accuracy": "Share of evaluation records classified correctly.",
    "precision": "Macro average: precision computed per class, then averaged with equal weight.",
    "recall": "Macro average: recall computed per class, then averaged with equal weight.",
    "f1": "Macro average of the per-class F1 scores.",
    "loss": "Mean cross-entropy on the evaluation split (lower is better).",
}


def confusion_matrix(y_true: np.ndarray, y_pred: np.ndarray, num_classes: int) -> np.ndarray:
    matrix = np.zeros((num_classes, num_classes), dtype=np.int64)
    np.add.at(matrix, (np.asarray(y_true, dtype=np.int64), np.asarray(y_pred, dtype=np.int64)), 1)
    return matrix


def cross_entropy_sum(probabilities: np.ndarray, y_true: np.ndarray) -> float:
    picked = probabilities[np.arange(len(y_true)), np.asarray(y_true, dtype=np.int64)]
    return float(-np.sum(np.log(np.clip(picked, 1e-12, 1.0))))


def evaluate_probabilities(probabilities: np.ndarray, y_true: np.ndarray) -> EvalResult:
    num_classes = probabilities.shape[1]
    predictions = np.argmax(probabilities, axis=1)
    return EvalResult(
        confusion=confusion_matrix(y_true, predictions, num_classes),
        loss_sum=cross_entropy_sum(probabilities, y_true),
        num_samples=int(len(y_true)),
    )


def pool_evaluations(results: Iterable[EvalResult]) -> EvalResult:
    """Sum sufficient statistics from several hospitals into one evaluation."""
    results = list(results)
    if not results:
        raise ValueError("No evaluation results to pool")
    shape = results[0].confusion.shape
    for result in results:
        if result.confusion.shape != shape:
            raise ValueError("Evaluation results use different class counts")
    return EvalResult(
        confusion=np.sum([r.confusion for r in results], axis=0),
        loss_sum=float(sum(r.loss_sum for r in results)),
        num_samples=int(sum(r.num_samples for r in results)),
    )


def _safe_div(numerator: float, denominator: float) -> float:
    return float(numerator / denominator) if denominator > 0 else 0.0


def per_class_metrics(confusion: np.ndarray, class_names: Iterable[str]) -> List[dict]:
    rows = []
    for index, name in enumerate(class_names):
        tp = float(confusion[index, index])
        fp = float(confusion[:, index].sum() - tp)
        fn = float(confusion[index, :].sum() - tp)
        precision = _safe_div(tp, tp + fp)
        recall = _safe_div(tp, tp + fn)
        rows.append(
            {
                "class_name": name,
                "support": int(confusion[index, :].sum()),
                "precision": precision,
                "recall": recall,
                "f1": _safe_div(2 * precision * recall, precision + recall),
            }
        )
    return rows


def metrics_from_evaluation(result: EvalResult, task: TaskSpec) -> Dict[str, object]:
    """Turn pooled sufficient statistics into the metrics shown in the UI."""
    confusion = np.asarray(result.confusion, dtype=np.int64)
    total = int(confusion.sum())
    per_class = per_class_metrics(confusion, task.class_names)
    if task.task_type == "binary":
        positive = per_class[1]
        precision, recall, f1 = positive["precision"], positive["recall"], positive["f1"]
        averaging = f"positive class ({task.class_names[1]})"
    else:
        precision = float(np.mean([row["precision"] for row in per_class]))
        recall = float(np.mean([row["recall"] for row in per_class]))
        f1 = float(np.mean([row["f1"] for row in per_class]))
        averaging = "macro average over classes"
    return {
        "accuracy": _safe_div(float(np.trace(confusion)), total),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "loss": _safe_div(result.loss_sum, result.num_samples),
        "num_samples": int(result.num_samples),
        "averaging": averaging,
        "per_class": per_class,
        "confusion": confusion.tolist(),
    }
