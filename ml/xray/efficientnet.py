"""EfficientNet-B3 for chest X-ray classification (PyTorch / torchvision).

Set ``XRAY_PRETRAINED=true`` to start version 0 from ImageNet weights. That
needs an internet connection the first time, so it is off by default; without
it the network trains from random initialisation, which is slow to converge on
small datasets.
"""

from __future__ import annotations

import os

import numpy as np
import torch
from torch import nn

from ml.common.tasks import XRAY_TASK
from ml.common.torch_adapter import TorchModelAdapter
from ml.xray.preprocess import prepare_xray

_IMAGENET_MEAN = (0.485, 0.456, 0.406)
_IMAGENET_STD = (0.229, 0.224, 0.225)


class XrayEfficientNetB3(nn.Module):
    def __init__(self, num_classes: int, pretrained: bool = False):
        super().__init__()
        from torchvision.models import EfficientNet_B3_Weights, efficientnet_b3

        weights = EfficientNet_B3_Weights.IMAGENET1K_V1 if pretrained else None
        self.backbone = efficientnet_b3(weights=weights)
        in_features = self.backbone.classifier[1].in_features
        self.backbone.classifier[1] = nn.Linear(in_features, num_classes)
        # Not persistent: these constants are not model parameters and must not
        # appear in the weights that hospitals exchange.
        self.register_buffer("mean", torch.tensor(_IMAGENET_MEAN).view(1, 3, 1, 1), persistent=False)
        self.register_buffer("std", torch.tensor(_IMAGENET_STD).view(1, 3, 1, 1), persistent=False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:  # x: [batch, 1, H, W] in [0, 1]
        x = x.expand(-1, 3, -1, -1)
        x = (x - self.mean) / self.std
        return self.backbone(x)

    def gradcam_layers(self) -> list:
        """Convolutional feature blocks, shallowest first, as (name, module) pairs.

        Grad-CAM picks the deepest one whose map is fine enough to show where
        the model looked (see ``analytics.explainability.gradcam``).
        """
        return [(f"backbone.features[{i}]", block) for i, block in enumerate(self.backbone.features)]


class EfficientNetB3Adapter(TorchModelAdapter):
    modality = "xray"
    architecture = "EfficientNet-B3"

    def __init__(self):
        super().__init__(XRAY_TASK)
        self.pretrained = os.getenv("XRAY_PRETRAINED", "false").strip().lower() in ("1", "true", "yes")
        start = "ImageNet-pretrained" if self.pretrained else "randomly initialised"
        self.summary = (
            f"torchvision EfficientNet-B3 ({start}) with a {self.task.num_classes}-way classification head. "
            "Greyscale images are replicated to three channels."
        )

    def build_model(self, for_init: bool = False) -> nn.Module:
        # Pretrained weights are only fetched when creating version 0; every
        # later load overwrites all parameters with federated weights anyway.
        return XrayEfficientNetB3(self.task.num_classes, pretrained=self.pretrained and for_init)

    def to_input(self, X: np.ndarray) -> torch.Tensor:
        images = np.ascontiguousarray(prepare_xray(X))
        return torch.from_numpy(images).unsqueeze(1)
