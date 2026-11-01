"""Grad-CAM for the PyTorch X-ray model.

Requires PyTorch and an adapter whose network exposes ``gradcam_layers()``
(EfficientNet-B3 does). For other backends callers fall back to occlusion
sensitivity and label the result accordingly.

Grad-CAM is usually computed on the last convolutional block. EfficientNet-B3
shrinks its input 32-fold by then: a 224 px radiograph gives a 7x7 map, but a
64 px simulated phantom gives 2x2, which upsamples to a smooth wash over the
whole image and shows nothing. So the deepest block whose map is at least
``MIN_CAM_CELLS`` wide is used, and the result says which block that was.
"""

from __future__ import annotations

import numpy as np

METHOD_NAME = "Grad-CAM on the deepest convolutional block with at least a 7x7 map"
MIN_CAM_CELLS = 7


def supports_gradcam(adapter) -> bool:
    return getattr(adapter, "backend", "") == "pytorch" and adapter.modality == "xray"


def grad_cam(adapter, weights, image: np.ndarray, target_class: int | None = None) -> dict:
    """Class-activation heat map for one image of shape [H, W].

    Returns ``heatmap`` scaled to [0, 1] at the input resolution, and the name
    of the ``layer`` it was computed on.
    """
    import torch
    import torch.nn.functional as F

    model = adapter.load_model(weights)
    model.eval()
    candidates = model.gradcam_layers()
    captured = {}

    def keep_activation(name):
        def hook(_module, _inputs, output):
            output.retain_grad()
            captured[name] = output

        return hook

    handles = [module.register_forward_hook(keep_activation(name)) for name, module in candidates]
    try:
        inputs = adapter.to_input(np.asarray(image)[None])
        logits = model(inputs)
        probabilities = torch.softmax(logits, dim=1)[0]
        if target_class is None:
            target_class = int(probabilities.argmax().item())
        model.zero_grad()
        logits[0, target_class].backward()
    finally:
        for handle in handles:
            handle.remove()

    # Deepest block that is still fine enough; failing that, the finest one.
    fine_enough = [name for name, _ in candidates if min(captured[name].shape[-2:]) >= MIN_CAM_CELLS]
    layer = fine_enough[-1] if fine_enough else candidates[0][0]
    activation = captured[layer]
    gradient = activation.grad
    channel_weights = gradient.mean(dim=(2, 3), keepdim=True)
    cam = torch.relu((channel_weights * activation).sum(dim=1, keepdim=True))
    cam = F.interpolate(cam, size=inputs.shape[-2:], mode="bilinear", align_corners=False)[0, 0]
    cam = cam.detach()
    maximum = float(cam.max().item())
    if maximum > 0:
        cam = cam / maximum
    return {
        "heatmap": cam.cpu().numpy().astype(np.float64),
        "target_class": int(target_class),
        "probabilities": probabilities.detach().cpu().numpy().astype(np.float64),
        "layer": layer,
        "layer_resolution": list(activation.shape[-2:]),
    }
