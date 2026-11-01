"""Builds explanation payloads for each modality.

Every payload names the method that produced it and the model version it
explains. Nothing here invents values: if a method cannot run for the active
model, the caller receives ``ExplanationUnavailable`` with the reason.
"""

from __future__ import annotations

import base64
import io
import os
from typing import Optional

import numpy as np

from analytics.explainability import gradcam, occlusion, shapley


class ExplanationUnavailable(RuntimeError):
    """An explanation cannot be produced; the message says why."""


def explainer_backend() -> str:
    return os.getenv("EXPLAINER_BACKEND", "builtin").strip().lower()


def _prediction_block(probabilities: np.ndarray, class_names) -> dict:
    index = int(np.argmax(probabilities))
    return {
        "class_index": index,
        "class_name": class_names[index],
        "probability": float(probabilities[index]),
        "probabilities": [{"class_name": name, "probability": float(p)} for name, p in zip(class_names, probabilities)],
    }


def explain_ehr_record(
    adapter, weights, x: np.ndarray, background: np.ndarray, feature_meta: list, n_permutations: int = 32, seed: int = 0
) -> dict:
    """Individual explanation: how each feature moved this record's predicted risk."""
    output_index = 1  # probability of the positive class

    def predict(data: np.ndarray) -> np.ndarray:
        return adapter.predict_proba(weights, data)

    probabilities = predict(np.asarray(x, dtype=np.float32).reshape(1, -1))[0]
    if explainer_backend() == "shap-library":
        try:
            result = shapley.shap_library_values(predict, x, background, output_index)
        except ImportError as exc:
            raise ExplanationUnavailable(
                "EXPLAINER_BACKEND=shap-library but the 'shap' package is not installed."
            ) from exc
        values, base_value = result["values"], result["base_value"]
        method, n_perm = "SHAP KernelExplainer (shap library)", None
    else:
        result = shapley.shapley_values(predict, x, background, n_permutations, np.random.default_rng(seed))
        values, base_value = result["values"][:, output_index], float(result["base_value"][output_index])
        method, n_perm = shapley.METHOD_NAME, result["n_permutations"]

    contributions = []
    for meta, value, shap_value in zip(feature_meta, np.asarray(x).reshape(-1), values):
        contributions.append(
            {
                "feature": meta["name"],
                "label": meta["label"],
                "unit": meta["unit"],
                "value": float(value),
                "shap_value": float(shap_value),
                "direction": "raises" if shap_value > 0 else "lowers" if shap_value < 0 else "neutral",
            }
        )
    contributions.sort(key=lambda item: abs(item["shap_value"]), reverse=True)
    return {
        "scope": "individual",
        "modality": "ehr",
        "method": method,
        "explained_output": f"Predicted probability of '{adapter.task.class_names[output_index]}'",
        "prediction": _prediction_block(probabilities, adapter.task.class_names),
        "base_value": float(base_value),
        "contributions": contributions,
        "additivity": {
            "base_plus_contributions": float(base_value + float(np.sum(values))),
            "model_output": float(probabilities[output_index]),
        },
        "metadata": {"n_background": int(len(background)), "n_permutations": n_perm},
    }


def explain_ecg_beat(adapter, weights, signal: np.ndarray, sample_rate_hz: int) -> dict:
    def predict(data: np.ndarray) -> np.ndarray:
        return adapter.predict_proba(weights, data)

    probabilities = predict(np.asarray(signal, dtype=np.float32)[None])[0]
    target = int(np.argmax(probabilities))
    result = occlusion.occlusion_signal(predict, signal, target)
    importance = result["importance"]

    # Summarise the most influential stretch of the beat in milliseconds.
    window = result["window"]
    smoothed = np.convolve(importance, np.ones(window) / window, mode="same")
    centre = int(np.argmax(smoothed))
    start, end = max(0, centre - window // 2), min(len(importance), centre + window // 2)
    return {
        "scope": "individual",
        "modality": "ecg",
        "method": occlusion.SIGNAL_METHOD,
        "explained_output": f"Predicted probability of '{adapter.task.class_names[target]}'",
        "prediction": _prediction_block(probabilities, adapter.task.class_names),
        "signal": [round(float(v), 4) for v in np.asarray(signal).reshape(-1)],
        "importance": [round(float(v), 5) for v in importance],
        "sample_rate_hz": sample_rate_hz,
        "importance_unit": "drop in log-odds of the predicted class when the stretch is hidden",
        "importance_has_signal": bool(np.max(importance) > 1e-6),
        "most_influential_segment": {
            "start_ms": round(1000.0 * start / sample_rate_hz),
            "end_ms": round(1000.0 * end / sample_rate_hz),
            "mean_importance": float(importance[start:end].mean()) if end > start else 0.0,
        },
        "metadata": {
            "window_samples": window,
            "stride_samples": result["stride"],
            "evaluations": result["evaluations"],
        },
    }


def _png_base64(image: np.ndarray) -> str:
    from PIL import Image

    buffer = io.BytesIO()
    Image.fromarray(np.asarray(image, dtype=np.uint8)).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def explain_xray_image(adapter, weights, image: np.ndarray) -> dict:
    def predict(data: np.ndarray) -> np.ndarray:
        return adapter.predict_proba(weights, data)

    probabilities = predict(np.asarray(image)[None])[0]
    target = int(np.argmax(probabilities))
    if gradcam.supports_gradcam(adapter):
        result = gradcam.grad_cam(adapter, weights, image, target)
        heatmap, method = result["heatmap"], gradcam.METHOD_NAME
        rows, cols = result["layer_resolution"]
        metadata = {"target_layer": f"{result['layer']} ({rows}x{cols} map)"}
    else:
        result = occlusion.occlusion_image(predict, image, target)
        positive = np.clip(result["importance"], 0.0, None)
        heatmap = positive / positive.max() if positive.max() > 0 else positive
        method = occlusion.IMAGE_METHOD
        metadata = {
            "patch": result["patch"],
            "stride": result["stride"],
            "evaluations": result["evaluations"],
            "note": "Grad-CAM needs the PyTorch EfficientNet-B3 model; occlusion sensitivity is shown instead.",
        }
    return {
        "scope": "individual",
        "modality": "xray",
        "method": method,
        "explained_output": f"Predicted probability of '{adapter.task.class_names[target]}'",
        "prediction": _prediction_block(probabilities, adapter.task.class_names),
        "image_png_base64": _png_base64(image),
        "heatmap": [[round(float(v), 3) for v in row] for row in heatmap],
        "heatmap_has_signal": bool(np.max(heatmap) > 0),
        "metadata": metadata,
    }


def local_global_importance(
    adapter,
    weights,
    X: np.ndarray,
    background: np.ndarray,
    max_records: int = 24,
    n_permutations: int = 8,
    seed: int = 0,
) -> Optional[dict]:
    """Aggregate feature importance computed inside a hospital node (EHR only)."""
    if adapter.modality != "ehr" or len(X) == 0 or len(background) == 0:
        return None
    rng = np.random.default_rng(seed)
    records = X[rng.choice(len(X), size=min(max_records, len(X)), replace=False)]
    reference = background[rng.choice(len(background), size=min(24, len(background)), replace=False)]
    result = shapley.global_importance(
        lambda data: adapter.predict_proba(weights, data),
        records,
        reference,
        output_index=1,
        n_permutations=n_permutations,
        rng=rng,
    )
    return {
        "mean_abs": [float(v) for v in result["mean_abs"]],
        "direction": [float(v) for v in result["direction"]],
        "num_records": result["num_records"],
        "n_background": result["n_background"],
        "n_permutations": result["n_permutations"],
        "method": shapley.METHOD_NAME,
    }


def pool_global_importance(reports: list, feature_meta: list) -> Optional[dict]:
    """Combine per-hospital aggregates, weighting each hospital by records explained."""
    reports = [r for r in reports if r]
    if not reports:
        return None
    weights = np.array([r["num_records"] for r in reports], dtype=np.float64)
    weights = weights / weights.sum()
    mean_abs = np.sum([w * np.asarray(r["mean_abs"]) for w, r in zip(weights, reports)], axis=0)
    direction = np.sum([w * np.asarray(r["direction"]) for w, r in zip(weights, reports)], axis=0)
    features = []
    for meta, importance, sign in zip(feature_meta, mean_abs, direction):
        features.append(
            {
                "feature": meta["name"],
                "label": meta["label"],
                "unit": meta["unit"],
                "mean_abs_shap": float(importance),
                "direction": float(sign),
                "tendency": (
                    "higher values raise predicted risk"
                    if sign > 0.15
                    else "higher values lower predicted risk"
                    if sign < -0.15
                    else "no consistent direction"
                ),
            }
        )
    features.sort(key=lambda item: item["mean_abs_shap"], reverse=True)
    return {
        "scope": "global",
        "modality": "ehr",
        "method": reports[0]["method"],
        "features": features,
        "metadata": {
            "hospitals_contributing": len(reports),
            "records_explained": int(sum(r["num_records"] for r in reports)),
            "n_permutations": reports[0]["n_permutations"],
            "aggregation": "Per-hospital mean |SHAP| values, weighted by records explained at each hospital.",
        },
    }
