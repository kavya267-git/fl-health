"""A hospital's federated-learning client.

One ``HospitalNode`` owns one hospital's data directory. During a round it:

1. joins the round and learns the training configuration;
2. downloads the current global weights;
3. trains locally on its own data;
4. optionally clips and noises the update (differential privacy prototype);
5. sends back *only* model weights, a sample count and summary metrics;
6. later downloads the aggregated model, evaluates it on its local held-out
   split and returns a confusion matrix (plus, for EHR, aggregate feature
   importance).

Raw records never leave this class: nothing passed to the transport contains
patient-level data.
"""

from __future__ import annotations

import zlib
from pathlib import Path
from typing import Optional, Protocol

import numpy as np

from analytics.explainability.service import local_global_importance
from analytics.privacy.dp import DPConfig, privatize_update
from ml.common.datasets import load_local_dataset, local_data_summary
from ml.common.types import TrainConfig
from ml.common.weights import architecture_signature, weights_from_bytes, weights_to_bytes
from ml.registry import get_adapter
from ml.training.local_trainer import evaluate_on_local_data, train_on_local_data


class CoordinatorTransport(Protocol):
    """How a node reaches the coordinator (in-process in simulation, HTTP otherwise)."""

    def join_round(self, round_id: str, hospital_id: str, data_summary: dict) -> dict: ...

    def fetch_global_model(self, round_id: str, hospital_id: str, which: str) -> bytes: ...

    def submit_update(
        self,
        round_id: str,
        hospital_id: str,
        payload: bytes,
        num_samples: int,
        metrics: dict,
        dp_report: dict,
        architecture_signature: str,
    ) -> dict: ...

    def submit_evaluation(
        self, round_id: str, hospital_id: str, evaluation: dict, explanation: Optional[dict]
    ) -> dict: ...

    def report_failure(self, round_id: str, hospital_id: str, stage: str, message: str) -> None: ...


class HospitalNode:
    def __init__(
        self, hospital_id: str, data_dir: Path, transport: CoordinatorTransport, backend: Optional[str] = None
    ):
        self.hospital_id = hospital_id
        self.data_dir = Path(data_dir)
        self.transport = transport
        self.backend = backend
        #: Size of the last update sent and the last evaluation computed, for the node's console.
        self.last_update_bytes: Optional[int] = None
        self.last_evaluation = None

    # ------------------------------------------------------------- metadata
    def data_summary(self) -> dict:
        """Counts and provenance only."""
        return local_data_summary(self.data_dir)

    # ---------------------------------------------------------------- round
    def join(self, round_id: str) -> dict:
        return self.transport.join_round(round_id, self.hospital_id, self.data_summary())

    def train_and_submit(self, round_id: str, round_info: dict) -> dict:
        modality = round_info["modality"]
        adapter = get_adapter(modality, self.backend)
        global_weights = weights_from_bytes(self.transport.fetch_global_model(round_id, self.hospital_id, "base"))

        training = round_info["training"]
        seed = int(training.get("seed", 0)) + zlib.crc32(f"{self.hospital_id}:{round_id}".encode()) % 100_000
        config = TrainConfig(
            local_epochs=int(training["local_epochs"]),
            batch_size=int(training["batch_size"]),
            learning_rate=float(training["learning_rate"]),
            seed=seed,
            # Optional; rounds started from the dashboard do not set them.
            class_weighting=str(training.get("class_weighting", "none")),
            proximal_mu=float(training.get("proximal_mu", 0.0)),
        )
        output = train_on_local_data(self.data_dir, modality, global_weights, config, self.backend)

        dp_config = DPConfig.from_dict(round_info.get("differential_privacy"))
        private_weights, dp_report = privatize_update(
            global_weights, output.weights, dp_config, np.random.default_rng(seed + 1)
        )
        metrics = {
            "training_history": output.history,
            "local_validation": output.local_validation,
            "duration_seconds": output.duration_seconds,
            "dataset_source": output.dataset_source,
            "backend": adapter.backend,
            "architecture": adapter.architecture,
        }
        payload = weights_to_bytes(private_weights)
        self.last_update_bytes = len(payload)
        return self.transport.submit_update(
            round_id,
            self.hospital_id,
            payload,
            output.num_samples,
            metrics,
            dp_report,
            architecture_signature(private_weights, f"{adapter.backend}:{adapter.architecture}"),
        )

    def evaluate_and_report(self, round_id: str, round_info: dict) -> dict:
        modality = round_info["modality"]
        adapter = get_adapter(modality, self.backend)
        weights = weights_from_bytes(self.transport.fetch_global_model(round_id, self.hospital_id, "result"))
        evaluation = evaluate_on_local_data(self.data_dir, modality, weights, self.backend)
        self.last_evaluation = evaluation

        explanation = None
        if modality == "ehr" and round_info.get("explainability", {}).get("global_importance", True):
            validation = load_local_dataset(self.data_dir, modality, "val")
            train = load_local_dataset(self.data_dir, modality, "train")
            explanation = local_global_importance(
                adapter,
                weights,
                validation.X,
                train.X,
                seed=zlib.crc32(f"{self.hospital_id}:{round_id}:explain".encode()) % 100_000,
            )
        return self.transport.submit_evaluation(round_id, self.hospital_id, evaluation.to_dict(), explanation)

    def run_round(self, round_id: str) -> None:
        """Convenience for a stand-alone node: join, train, submit. Evaluation is a second call."""
        stage = "join"
        try:
            info = self.join(round_id)
            stage = "training"
            self.train_and_submit(round_id, info)
        except Exception as exc:
            self.transport.report_failure(round_id, self.hospital_id, stage, str(exc))
            raise
