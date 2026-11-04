"""A small global LSTM forecaster: one network trained on many weekly series at once.

Each series is divided by its own scale (the caller passes it, e.g. the mean of the series over its training
weeks) so that large and small regions train on the same footing. The network reads the last ``input_weeks``
scaled values and predicts the next ``horizon`` weeks directly (one output per week ahead). Forecasts are
multiplied back by the scale and clipped at 0. It gives no interval of its own; callers derive one from
validation errors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence

import numpy as np


@dataclass(frozen=True)
class LSTMSettings:
    input_weeks: int = 8
    hidden: int = 32
    layers: int = 1
    epochs: int = 150
    batch_size: int = 64
    learning_rate: float = 0.005
    seed: int = 0


def training_windows(series: Sequence[np.ndarray], scales: Sequence[float], input_weeks: int, horizon: int):
    """Every (input, target) pair whose target weeks all lie inside the given series, scaled."""
    inputs, targets = [], []
    for values, scale in zip(series, scales):
        z = np.asarray(values, dtype=np.float64) / scale
        for end in range(input_weeks, len(z) - horizon + 1):
            inputs.append(z[end - input_weeks : end])
            targets.append(z[end : end + horizon])
    return np.asarray(inputs, dtype=np.float32), np.asarray(targets, dtype=np.float32)


class GlobalLSTM:
    name = "LSTM (global)"

    def __init__(self, settings: LSTMSettings = LSTMSettings(), horizon: int = 4):
        self.settings = settings
        self.horizon = horizon

    def _network(self):
        import torch
        from torch import nn

        settings, horizon = self.settings, self.horizon

        class Net(nn.Module):
            def __init__(self):
                super().__init__()
                self.lstm = nn.LSTM(1, settings.hidden, num_layers=settings.layers, batch_first=True)
                self.head = nn.Linear(settings.hidden, horizon)

            def forward(self, x: torch.Tensor) -> torch.Tensor:  # x: [batch, weeks]
                output, _ = self.lstm(x.unsqueeze(-1))
                return self.head(output[:, -1])

        return Net()

    def fit(self, series: Sequence[np.ndarray], scales: Sequence[float]) -> "GlobalLSTM":
        import torch

        settings = self.settings
        inputs, targets = training_windows(series, scales, settings.input_weeks, self.horizon)
        if len(inputs) == 0:
            raise ValueError("The series are too short to train the LSTM")
        torch.manual_seed(settings.seed)
        rng = np.random.default_rng(settings.seed)
        self._net = self._network()
        optimiser = torch.optim.Adam(self._net.parameters(), lr=settings.learning_rate)
        x_all, y_all = torch.from_numpy(inputs), torch.from_numpy(targets)
        self._net.train()
        for _ in range(settings.epochs):
            order = torch.from_numpy(rng.permutation(len(inputs)))
            for start in range(0, len(order), settings.batch_size):
                batch = order[start : start + settings.batch_size]
                optimiser.zero_grad()
                loss = torch.mean((self._net(x_all[batch]) - y_all[batch]) ** 2)
                loss.backward()
                optimiser.step()
        self._net.eval()
        return self

    def predict(self, series: Sequence[np.ndarray], scales: Sequence[float]) -> List[np.ndarray]:
        """Forecast ``horizon`` weeks after the end of each series (in counts, clipped at 0)."""
        import torch

        weeks = self.settings.input_weeks
        windows = np.asarray(
            [np.asarray(values, dtype=np.float64)[-weeks:] / scale for values, scale in zip(series, scales)],
            dtype=np.float32,
        )
        with torch.no_grad():
            scaled = self._net(torch.from_numpy(windows)).numpy().astype(np.float64)
        return [np.clip(row * scale, 0.0, None) for row, scale in zip(scaled, scales)]
