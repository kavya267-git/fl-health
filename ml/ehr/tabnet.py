"""TabNet for structured EHR data (PyTorch).

A compact implementation of Arik & Pfister, "TabNet: Attentive Interpretable
Tabular Learning" (2019): sequential attention steps, each choosing a sparse
subset of features through a sparsemax mask, with ghost batch normalisation
and gated linear unit (GLU) feature transformers.
"""

from __future__ import annotations

import math
from typing import List, Optional

import numpy as np
import torch
from torch import nn

from ml.common.tasks import EHR_TASK
from ml.common.torch_adapter import TorchModelAdapter
from ml.ehr.features import NUM_EHR_FEATURES, standardize_ehr


class Sparsemax(nn.Module):
    """Sparsemax activation over the last dimension (Martins & Astudillo, 2016)."""

    def forward(self, z: torch.Tensor) -> torch.Tensor:
        z_sorted, _ = torch.sort(z, dim=-1, descending=True)
        k = torch.arange(1, z.size(-1) + 1, device=z.device, dtype=z.dtype)
        z_cumsum = z_sorted.cumsum(dim=-1)
        support = (1 + k * z_sorted) > z_cumsum
        k_support = support.sum(dim=-1, keepdim=True).clamp(min=1)
        tau = (z_cumsum.gather(-1, k_support - 1) - 1) / k_support.to(z.dtype)
        return torch.clamp(z - tau, min=0)


class GhostBatchNorm(nn.Module):
    """Batch normalisation applied over small virtual batches."""

    def __init__(self, dim: int, virtual_batch_size: int = 64, momentum: float = 0.02):
        super().__init__()
        self.virtual_batch_size = virtual_batch_size
        self.bn = nn.BatchNorm1d(dim, momentum=momentum)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if not self.training or x.size(0) <= self.virtual_batch_size:
            return self.bn(x)
        chunks = x.chunk(math.ceil(x.size(0) / self.virtual_batch_size), dim=0)
        return torch.cat([self.bn(chunk) for chunk in chunks], dim=0)


class GLULayer(nn.Module):
    """Linear -> ghost batch norm -> gated linear unit."""

    def __init__(
        self, in_dim: int, out_dim: int, shared_fc: Optional[nn.Linear], virtual_batch_size: int, momentum: float
    ):
        super().__init__()
        self.out_dim = out_dim
        if shared_fc is None:
            self.fc = nn.Linear(in_dim, 2 * out_dim, bias=False)
            self._shared = None
        else:
            # Kept in a plain list so the shared layer is registered (and
            # serialised) exactly once, by the owning TabNet module.
            self.fc = None
            self._shared = [shared_fc]
        self.bn = GhostBatchNorm(2 * out_dim, virtual_batch_size, momentum)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        fc = self.fc if self.fc is not None else self._shared[0]
        x = self.bn(fc(x))
        return x[:, : self.out_dim] * torch.sigmoid(x[:, self.out_dim :])


class FeatureTransformer(nn.Module):
    def __init__(
        self,
        in_dim: int,
        out_dim: int,
        shared_fcs: List[nn.Linear],
        n_independent: int,
        virtual_batch_size: int,
        momentum: float,
    ):
        super().__init__()
        layers = []
        current = in_dim
        for fc in shared_fcs:
            layers.append(GLULayer(current, out_dim, fc, virtual_batch_size, momentum))
            current = out_dim
        for _ in range(n_independent):
            layers.append(GLULayer(current, out_dim, None, virtual_batch_size, momentum))
            current = out_dim
        self.layers = nn.ModuleList(layers)
        self.scale = math.sqrt(0.5)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out = self.layers[0](x)
        for layer in self.layers[1:]:
            out = (out + layer(out)) * self.scale
        return out


class AttentiveTransformer(nn.Module):
    def __init__(self, attention_dim: int, input_dim: int, virtual_batch_size: int, momentum: float):
        super().__init__()
        self.fc = nn.Linear(attention_dim, input_dim, bias=False)
        self.bn = GhostBatchNorm(input_dim, virtual_batch_size, momentum)
        self.sparsemax = Sparsemax()

    def forward(self, prior: torch.Tensor, attention: torch.Tensor) -> torch.Tensor:
        return self.sparsemax(self.bn(self.fc(attention)) * prior)


class TabNet(nn.Module):
    def __init__(
        self,
        input_dim: int,
        num_classes: int,
        n_d: int = 16,
        n_a: int = 16,
        n_steps: int = 3,
        gamma: float = 1.3,
        n_shared: int = 2,
        n_independent: int = 2,
        virtual_batch_size: int = 64,
        momentum: float = 0.02,
    ):
        super().__init__()
        self.input_dim = input_dim
        self.n_d, self.n_a, self.n_steps, self.gamma = n_d, n_a, n_steps, gamma
        hidden = n_d + n_a

        self.initial_bn = nn.BatchNorm1d(input_dim, momentum=0.01)
        shared = []
        for index in range(n_shared):
            shared.append(nn.Linear(input_dim if index == 0 else hidden, 2 * hidden, bias=False))
        self.shared = nn.ModuleList(shared)

        def transformer() -> FeatureTransformer:
            return FeatureTransformer(input_dim, hidden, list(self.shared), n_independent, virtual_batch_size, momentum)

        self.initial_transformer = transformer()
        self.step_transformers = nn.ModuleList([transformer() for _ in range(n_steps)])
        self.attentive = nn.ModuleList(
            [AttentiveTransformer(n_a, input_dim, virtual_batch_size, momentum) for _ in range(n_steps)]
        )
        self.head = nn.Linear(n_d, num_classes)
        self.last_sparsity_loss: Optional[torch.Tensor] = None
        self.last_masks: List[torch.Tensor] = []

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.initial_bn(x)
        prior = torch.ones_like(x)
        attention = self.initial_transformer(x)[:, self.n_d :]
        decision = torch.zeros(x.size(0), self.n_d, device=x.device, dtype=x.dtype)
        entropy = torch.zeros((), device=x.device, dtype=x.dtype)
        masks = []
        for step in range(self.n_steps):
            mask = self.attentive[step](prior, attention)
            entropy = entropy + torch.mean(torch.sum(-mask * torch.log(mask + 1e-15), dim=1))
            prior = prior * (self.gamma - mask)
            out = self.step_transformers[step](mask * x)
            decision = decision + torch.relu(out[:, : self.n_d])
            attention = out[:, self.n_d :]
            masks.append(mask)
        self.last_sparsity_loss = entropy / self.n_steps
        self.last_masks = masks
        return self.head(decision)


class TabNetAdapter(TorchModelAdapter):
    modality = "ehr"
    architecture = "TabNet"
    summary = (
        "TabNet (3 attention steps, 16-dimensional decision and attention embeddings, "
        "sparsemax feature masks, ghost batch normalisation) on 14 structured EHR features."
    )
    sparsity_weight = 1e-3

    def __init__(self):
        super().__init__(EHR_TASK)

    def build_model(self, for_init: bool = False) -> nn.Module:
        return TabNet(NUM_EHR_FEATURES, self.task.num_classes)

    def to_input(self, X: np.ndarray) -> torch.Tensor:
        return torch.from_numpy(np.ascontiguousarray(standardize_ehr(X)))

    def regulariser(self, model: nn.Module) -> Optional[torch.Tensor]:
        if getattr(model, "last_sparsity_loss", None) is None:
            return None
        return self.sparsity_weight * model.last_sparsity_loss
