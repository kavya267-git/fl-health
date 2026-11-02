"""CNN + BiLSTM for single-beat ECG classification (PyTorch).

The 1-D convolutions pick up local waveform shape (QRS width, P and T waves);
the bidirectional LSTM models how those local patterns follow one another
across the beat.
"""

from __future__ import annotations

import numpy as np
import torch
from torch import nn

from ml.common.tasks import ECG_TASK
from ml.common.torch_adapter import TorchModelAdapter
from ml.ecg.preprocess import ECG_BEAT_LENGTH, prepare_ecg


class CNNBiLSTM(nn.Module):
    def __init__(self, num_classes: int, lstm_hidden: int = 64, dropout: float = 0.2, rr_inputs: int = 0):
        super().__init__()
        #: Extra per-beat inputs (e.g. RR intervals) stored after the beat samples and fed to the classifier.
        self.rr_inputs = rr_inputs
        self.features = nn.Sequential(
            nn.Conv1d(1, 32, kernel_size=7, padding=3),
            nn.BatchNorm1d(32),
            nn.ReLU(inplace=True),
            nn.MaxPool1d(2),
            nn.Conv1d(32, 64, kernel_size=5, padding=2),
            nn.BatchNorm1d(64),
            nn.ReLU(inplace=True),
            nn.MaxPool1d(2),
            nn.Conv1d(64, 64, kernel_size=3, padding=1),
            nn.BatchNorm1d(64),
            nn.ReLU(inplace=True),
        )
        self.lstm = nn.LSTM(input_size=64, hidden_size=lstm_hidden, batch_first=True, bidirectional=True)
        self.dropout = nn.Dropout(dropout)
        self.head = nn.Linear(2 * lstm_hidden + rr_inputs, num_classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:  # x: [batch, 1, samples (+ rr_inputs)]
        extra = None
        if self.rr_inputs:
            x, extra = x[:, :, : -self.rr_inputs], x[:, 0, -self.rr_inputs :]
        features = self.features(x)  # [batch, 64, steps]
        sequence, _ = self.lstm(features.transpose(1, 2))  # [batch, steps, 2 * hidden]
        pooled = self.dropout(sequence.mean(dim=1))
        if extra is not None:
            pooled = torch.cat([pooled, extra], dim=1)
        return self.head(pooled)


class CNNBiLSTMAdapter(TorchModelAdapter):
    modality = "ecg"
    architecture = "CNN-BiLSTM"
    summary = (
        "Three 1-D convolution blocks (32, 64, 64 channels) feeding a bidirectional LSTM "
        "(64 units per direction), mean-pooled over time, on 187-sample beat windows."
    )

    def __init__(self):
        super().__init__(ECG_TASK)

    def build_model(self, for_init: bool = False) -> nn.Module:
        return CNNBiLSTM(self.task.num_classes)

    def to_input(self, X: np.ndarray) -> torch.Tensor:
        beats = np.ascontiguousarray(prepare_ecg(X))
        return torch.from_numpy(beats).unsqueeze(1)


class CNNBiLSTMRRAdapter(CNNBiLSTMAdapter):
    """CNN-BiLSTM plus three RR-interval inputs per beat (experiment 1f; not used by the platform).

    Each input row is the 187 beat samples followed by pre-RR, post-RR and local average RR, each relative
    to the record's average RR. The RR values join the mean-pooled BiLSTM output before the final layer.
    """

    architecture = "CNN-BiLSTM+RR"
    rr_inputs = 3
    summary = CNNBiLSTMAdapter.summary + " Three RR-interval inputs join the pooled output before the classifier."

    def build_model(self, for_init: bool = False) -> nn.Module:
        return CNNBiLSTM(self.task.num_classes, rr_inputs=self.rr_inputs)

    def to_input(self, X: np.ndarray) -> torch.Tensor:
        X = np.asarray(X, dtype=np.float32)
        if X.ndim != 2 or X.shape[1] != ECG_BEAT_LENGTH + self.rr_inputs:
            raise ValueError(f"Input must have shape [n, {ECG_BEAT_LENGTH + self.rr_inputs}], got {X.shape}")
        rows = np.concatenate([prepare_ecg(X[:, :ECG_BEAT_LENGTH]), X[:, ECG_BEAT_LENGTH:]], axis=1)
        return torch.from_numpy(np.ascontiguousarray(rows)).unsqueeze(1)
