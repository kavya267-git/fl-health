"""Serialisation, hashing and compatibility checks for model weights.

Weights travel as an ``.npz`` archive of plain arrays. It is loaded with
``allow_pickle=False`` so a model update can never execute code on the
coordinator, unlike a pickled checkpoint.
"""

from __future__ import annotations

import hashlib
import io
from typing import Iterable

import numpy as np

from ml.common.types import Weights


class IncompatibleWeightsError(ValueError):
    """Raised when two sets of weights do not describe the same architecture."""


def weights_to_bytes(weights: Weights) -> bytes:
    buffer = io.BytesIO()
    # Sorted keys make the byte stream (and therefore the hash) deterministic.
    np.savez(buffer, **{key: np.asarray(weights[key]) for key in sorted(weights)})
    return buffer.getvalue()


def weights_from_bytes(payload: bytes) -> Weights:
    try:
        with np.load(io.BytesIO(payload), allow_pickle=False) as archive:
            return {key: np.array(archive[key]) for key in archive.files}
    except Exception as exc:  # zipfile.BadZipFile, ValueError (pickle refused), ...
        raise IncompatibleWeightsError(f"Payload is not a valid weights archive: {exc}") from exc


def weights_sha256(weights: Weights) -> str:
    """Content hash that does not depend on the container format."""
    digest = hashlib.sha256()
    for key in sorted(weights):
        array = np.ascontiguousarray(weights[key])
        digest.update(key.encode("utf-8"))
        digest.update(str(array.dtype).encode("utf-8"))
        digest.update(str(array.shape).encode("utf-8"))
        digest.update(array.tobytes())
    return digest.hexdigest()


def _kind(dtype: np.dtype) -> str:
    return "float" if np.issubdtype(dtype, np.floating) else "int"


def architecture_signature(weights: Weights, architecture: str = "") -> str:
    """Hash of tensor names, shapes and numeric kinds.

    Two updates may be averaged only if their signatures are identical. The
    values of the weights do not affect the signature.
    """
    digest = hashlib.sha256()
    digest.update(architecture.encode("utf-8"))
    for key in sorted(weights):
        array = np.asarray(weights[key])
        digest.update(f"|{key}:{tuple(array.shape)}:{_kind(array.dtype)}".encode("utf-8"))
    return digest.hexdigest()


def count_parameters(weights: Weights, float_only: bool = True) -> int:
    total = 0
    for array in weights.values():
        array = np.asarray(array)
        if float_only and not np.issubdtype(array.dtype, np.floating):
            continue
        total += int(array.size)
    return total


def assert_same_structure(reference: Weights, candidate: Weights) -> None:
    missing = sorted(set(reference) - set(candidate))
    extra = sorted(set(candidate) - set(reference))
    if missing or extra:
        raise IncompatibleWeightsError(f"Tensor names differ (missing: {missing[:5]}, unexpected: {extra[:5]})")
    for key in reference:
        ref, cand = np.asarray(reference[key]), np.asarray(candidate[key])
        if ref.shape != cand.shape:
            raise IncompatibleWeightsError(f"Tensor '{key}' has shape {cand.shape}, expected {ref.shape}")
        if _kind(ref.dtype) != _kind(cand.dtype):
            raise IncompatibleWeightsError(f"Tensor '{key}' has dtype {cand.dtype}, expected a {_kind(ref.dtype)} type")


def all_finite(weights: Weights) -> bool:
    return all(
        bool(np.all(np.isfinite(array)))
        for array in weights.values()
        if np.issubdtype(np.asarray(array).dtype, np.floating)
    )


def float_keys(weights: Weights) -> Iterable[str]:
    return [k for k in sorted(weights) if np.issubdtype(np.asarray(weights[k]).dtype, np.floating)]


def l2_distance(a: Weights, b: Weights) -> float:
    """L2 norm of (a - b) over floating-point tensors."""
    total = 0.0
    for key in float_keys(a):
        diff = np.asarray(a[key], dtype=np.float64) - np.asarray(b[key], dtype=np.float64)
        total += float(np.sum(diff * diff))
    return float(np.sqrt(total))
