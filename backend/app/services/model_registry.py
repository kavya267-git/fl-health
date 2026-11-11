"""Global model registry: one lineage of versions per modality.

EHR, ECG and X-ray models are stored, versioned and aggregated separately.
Version 0 of each lineage is the untrained initial model; every completed
federated round adds one version.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from app.database import Database
from app.utils.errors import NotFoundError, UnavailableError
from app.utils.time import utc_now_iso
from ml.common.types import MODALITIES
from ml.common.weights import count_parameters, weights_from_bytes, weights_sha256, weights_to_bytes
from ml.registry import TARGET_ARCHITECTURES, BackendUnavailableError, get_adapter

STATUS_INITIAL = "INITIAL"
STATUS_ACTIVE = "ACTIVE"
STATUS_ARCHIVED = "ARCHIVED"
#: weights_path of a version whose weights are in the model_weights table.
DB_PREFIX = "db:"

Weights = Dict[str, Any]


class ModelRegistry:
    def __init__(
        self, db: Database, storage_path: Path, keep_versions: int = 5, seed: int = 0, in_database: bool = False
    ):
        self.db = db
        #: Keep weights in the model_weights table instead of files (hosts without a persistent disk).
        self.in_database = in_database
        self.storage_path = Path(storage_path)
        self.keep_versions = max(2, keep_versions)
        self.seed = seed
        (self.storage_path / "global").mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------- storage
    def _weights_file(self, modality: str, version: int) -> Path:
        return self.storage_path / "global" / f"{modality}_v{version:04d}.npz"

    def _insert_version(
        self,
        modality: str,
        version: int,
        weights: Weights,
        status: str,
        round_id: Optional[str],
        metrics: Optional[dict],
        dataset: Optional[dict],
        is_simulated: bool,
    ) -> Dict[str, Any]:
        adapter = get_adapter(modality)
        payload = weights_to_bytes(weights)
        if self.in_database:
            key = f"{modality}:v{version}"
            self.db.execute("DELETE FROM model_weights WHERE id = :id", {"id": key})
            self.db.insert("model_weights", {"id": key, "weights_blob": payload, "created_at": utc_now_iso()})
            path = f"{DB_PREFIX}{key}"
        else:
            path = self._weights_file(modality, version)
            path.write_bytes(payload)
        return self.db.insert(
            "model_registry",
            {
                "id": f"{modality}:v{version}",
                "modality": modality,
                "version": version,
                "architecture": adapter.architecture,
                "backend": adapter.backend,
                "architecture_signature": adapter.signature(weights),
                "num_parameters": count_parameters(weights),
                "round_id": round_id,
                "status": status,
                "weights_path": str(path),
                "weights_sha256": weights_sha256(weights),
                "size_bytes": len(payload),
                "metrics": metrics,
                "dataset": dataset,
                "is_simulated": is_simulated,
                "created_at": utc_now_iso(),
            },
        )

    # ------------------------------------------------------------ lifecycle
    def ensure_initial(self, modality: str, is_simulated: bool) -> Dict[str, Any]:
        """Create version 0, or start a fresh lineage if the architecture changed.

        The architecture changes when, for example, PyTorch is installed after
        the demo was first run with the NumPy reference models. Weights of the
        two are not interchangeable, so the lineage restarts from an untrained
        model instead of mixing them.
        """
        try:
            adapter = get_adapter(modality)
        except BackendUnavailableError as exc:
            raise UnavailableError(str(exc)) from exc
        latest = self.latest(modality)
        if latest is not None and latest["architecture_signature"] == adapter.signature():
            return latest
        version = 0 if latest is None else latest["version"] + 1
        if latest is not None:
            self.db.execute(
                "UPDATE model_registry SET status = :archived WHERE modality = :modality",
                {"archived": STATUS_ARCHIVED, "modality": modality},
            )
        weights = adapter.init_weights(self.seed)
        return self._insert_version(modality, version, weights, STATUS_INITIAL, None, None, None, is_simulated)

    def register_version(
        self, modality: str, weights: Weights, round_id: str, metrics: dict, dataset: dict, is_simulated: bool
    ) -> Dict[str, Any]:
        latest = self.latest(modality)
        version = 0 if latest is None else latest["version"] + 1
        self.db.execute(
            "UPDATE model_registry SET status = :archived WHERE modality = :modality",
            {"archived": STATUS_ARCHIVED, "modality": modality},
        )
        row = self._insert_version(modality, version, weights, STATUS_ACTIVE, round_id, metrics, dataset, is_simulated)
        self._prune(modality)
        return row

    def _prune(self, modality: str) -> None:
        """Keep weight files for the newest versions only; metadata is kept for all."""
        rows = self.db.fetch_all(
            "SELECT id, weights_path FROM model_registry WHERE modality = :modality AND weights_path IS NOT NULL "
            "ORDER BY version DESC",
            {"modality": modality},
        )
        for row in rows[self.keep_versions :]:
            if str(row["weights_path"]).startswith(DB_PREFIX):
                self.db.execute("DELETE FROM model_weights WHERE id = :id", {"id": row["weights_path"][len(DB_PREFIX):]})
            else:
                Path(row["weights_path"]).unlink(missing_ok=True)
            self.db.update("model_registry", {"weights_path": None}, {"id": row["id"]})

    # --------------------------------------------------------------- lookup
    def latest(self, modality: str) -> Optional[Dict[str, Any]]:
        return self.db.fetch_one(
            "SELECT * FROM model_registry WHERE modality = :modality ORDER BY version DESC LIMIT 1",
            {"modality": modality},
        )

    def get_version(self, modality: str, version: int) -> Dict[str, Any]:
        row = self.db.fetch_one(
            "SELECT * FROM model_registry WHERE modality = :modality AND version = :version",
            {"modality": modality, "version": version},
        )
        if row is None:
            raise NotFoundError(f"No {modality} model version {version}")
        return row

    def load_bytes(self, modality: str, version: int) -> bytes:
        row = self.get_version(modality, version)
        stored = row["weights_path"] or ""
        if stored.startswith(DB_PREFIX):
            blob = self.db.fetch_one("SELECT weights_blob FROM model_weights WHERE id = :id", {"id": stored[len(DB_PREFIX):]})
            if blob is not None:
                return bytes(blob["weights_blob"])
        if not stored or stored.startswith(DB_PREFIX) or not Path(stored).exists():
            raise UnavailableError(
                f"Weights for {modality} v{version} are no longer stored (only the newest "
                f"{self.keep_versions} versions keep their weights)."
            )
        return Path(row["weights_path"]).read_bytes()

    def load_weights(self, modality: str, version: int) -> Weights:
        return weights_from_bytes(self.load_bytes(modality, version))

    def versions(self, modality: str) -> List[Dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT * FROM model_registry WHERE modality = :modality ORDER BY version DESC",
            {"modality": modality},
        )

    # ---------------------------------------------------------- presentation
    def describe(self, modality: str) -> Dict[str, Any]:
        if modality not in MODALITIES:
            raise NotFoundError(f"Unknown model '{modality}'. Models are identified by modality: {list(MODALITIES)}")
        latest = self.latest(modality)
        if latest is None:
            raise NotFoundError(f"The {modality} model has not been initialised")
        description = get_adapter(modality).describe()
        trained = [v for v in self.versions(modality) if v["status"] != STATUS_INITIAL and v["metrics"]]
        return {
            "id": modality,
            "modality": modality,
            "architecture": latest["architecture"],
            "target_architecture": TARGET_ARCHITECTURES[modality],
            "backend": latest["backend"],
            "is_target_architecture": latest["architecture"] == TARGET_ARCHITECTURES[modality],
            "summary": description["summary"],
            "task": description["task"],
            "num_parameters": latest["num_parameters"],
            "architecture_signature": latest["architecture_signature"],
            "current_version": latest["version"],
            "training_status": "TRAINED" if latest["status"] == STATUS_ACTIVE else "NOT_TRAINED",
            "latest_round_id": latest["round_id"],
            "latest_metrics": latest["metrics"],
            "dataset": latest["dataset"],
            "last_updated": latest["created_at"],
            "trained_versions": len(trained),
            "is_simulated": latest["is_simulated"],
        }
