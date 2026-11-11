"""The hospital's local copy of the latest global model.

After a round completes, the node keeps the aggregated model it already downloaded to evaluate:

    <models_dir>/<modality>/global_latest.npz    the weights (the same .npz bytes the coordinator registered)
    <models_dir>/<modality>/global_latest.json   round, version, architecture, SHA-256, time, this hospital's F1
    <models_dir>/<modality>/global_previous.*    the copy it replaced

Nothing is sent anywhere: the file is the download the node made for its evaluation, written to its own disk.
Each file is written to a temporary name first and then renamed, so a crash never leaves half a file.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict

LATEST = "global_latest"
PREVIOUS = "global_previous"


def _write_atomic(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    with open(temporary, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def save_global_model(models_dir: Path, modality: str, payload: bytes, info: Dict[str, Any]) -> Path:
    """Save ``payload`` as the latest global model for ``modality``; the one it replaces becomes the previous."""
    folder = Path(models_dir) / modality
    folder.mkdir(parents=True, exist_ok=True)
    for suffix in (".npz", ".json"):
        latest = folder / f"{LATEST}{suffix}"
        if latest.exists():
            _write_atomic(folder / f"{PREVIOUS}{suffix}", latest.read_bytes())
    meta = {**info, "modality": modality, "sha256": hashlib.sha256(payload).hexdigest(), "size_bytes": len(payload)}
    _write_atomic(folder / f"{LATEST}.npz", payload)
    _write_atomic(folder / f"{LATEST}.json", (json.dumps(meta, indent=2) + "\n").encode("utf-8"))
    return folder / f"{LATEST}.npz"
