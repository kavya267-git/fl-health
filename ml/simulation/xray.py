"""Simulated chest-image phantoms.

SIMULATED DATA. These are geometric phantoms (a torso gradient, two dark lung
fields, a bright midline band) and not radiographs. A "finding" is one or two
soft bright blobs placed inside a lung field. They exist so the imaging
pipeline can be exercised end to end; they have no diagnostic meaning.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

XRAY_IMAGE_SIZE = 64


@dataclass(frozen=True)
class XrayProfile:
    prevalence: float = 0.4
    contrast: float = 1.0  # scanner contrast
    brightness: float = 0.0  # scanner offset
    noise: float = 0.035


def _ellipse(yy, xx, cy, cx, ry, rx, softness=0.08):
    distance = np.sqrt(((yy - cy) / ry) ** 2 + ((xx - cx) / rx) ** 2)
    return 1.0 / (1.0 + np.exp((distance - 1.0) / softness))


def _phantom(rng: np.random.Generator, finding: bool) -> np.ndarray:
    size = XRAY_IMAGE_SIZE
    yy, xx = np.mgrid[0:size, 0:size] / (size - 1.0)
    image = 0.55 + 0.10 * (1.0 - np.abs(xx - 0.5) * 2.0)  # torso, brighter at the midline
    image *= _ellipse(yy, xx, 0.52, 0.5, 0.62, 0.56, 0.05) * 0.9 + 0.1

    centres = []
    for side in (-1, 1):
        cy = 0.50 + rng.normal(0, 0.015)
        cx = 0.5 + side * (0.21 + rng.normal(0, 0.01))
        ry = 0.27 + rng.normal(0, 0.015)
        rx = 0.135 + rng.normal(0, 0.01)
        image -= 0.38 * _ellipse(yy, xx, cy, cx, ry, rx)
        centres.append((cy, cx, ry, rx))
    image += 0.16 * np.exp(-0.5 * ((xx - 0.5) / 0.035) ** 2)  # midline band

    if finding:
        for _ in range(int(rng.integers(1, 3))):
            cy, cx, ry, rx = centres[int(rng.integers(0, 2))]
            by = cy + rng.uniform(-0.6, 0.6) * ry
            bx = cx + rng.uniform(-0.5, 0.5) * rx
            radius = rng.uniform(0.035, 0.075)
            strength = rng.uniform(0.16, 0.30)
            image += strength * np.exp(-0.5 * (((yy - by) ** 2 + (xx - bx) ** 2) / radius**2))
    return image


def simulate_xray(n: int, rng: np.random.Generator, profile: XrayProfile = XrayProfile()):
    labels = rng.binomial(1, profile.prevalence, n).astype(np.int64)
    images = np.empty((n, XRAY_IMAGE_SIZE, XRAY_IMAGE_SIZE), dtype=np.uint8)
    for index, label in enumerate(labels):
        image = _phantom(rng, bool(label))
        image = (image - 0.5) * profile.contrast + 0.5 + profile.brightness
        image = image + rng.normal(0, profile.noise, image.shape)
        images[index] = np.clip(image * 255.0, 0, 255).astype(np.uint8)
    return images, labels
