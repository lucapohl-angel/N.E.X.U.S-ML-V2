"""High-specificity visual occupancy evidence for MLBB item slots."""

from __future__ import annotations

import cv2
import numpy as np
from numpy.typing import NDArray

from nexus_v2.schemas.result import ExtractionStatus

ImageArray = NDArray[np.uint8]


def item_occupancy_features(image: ImageArray) -> dict[str, float]:
    """Measure icon evidence inside the central circular item region."""

    height, width = image.shape[:2]
    yy, xx = np.ogrid[:height, :width]
    center_x = (width - 1) / 2.0
    center_y = (height - 1) / 2.0
    radius = min(width, height) * 0.42
    mask = (xx - center_x) ** 2 + (yy - center_y) ** 2 <= radius**2
    hsv = cv2.cvtColor(image, cv2.COLOR_RGB2HSV)
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 35, 110)
    saturation = np.asarray(hsv[:, :, 1][mask], dtype=np.float32)
    value = np.asarray(hsv[:, :, 2][mask], dtype=np.float32)
    grayscale = np.asarray(gray[mask], dtype=np.float32)
    edge_pixels = np.asarray(edges[mask] > 0, dtype=np.float32)
    return {
        "occupancy_saturation_mean": float(saturation.mean() / 255.0),
        "occupancy_value_std": float(value.std() / 255.0),
        "occupancy_grayscale_std": float(grayscale.std() / 255.0),
        "occupancy_edge_density": float(edge_pixels.mean()),
    }


def item_occupancy(image: ImageArray) -> tuple[ExtractionStatus, dict[str, float]]:
    """Classify a slot conservatively as empty, occupied, or uncertain."""

    scores = item_occupancy_features(image)
    empty = (
        scores["occupancy_saturation_mean"] >= 0.80
        and scores["occupancy_value_std"] <= 0.05
        and scores["occupancy_grayscale_std"] <= 0.05
        and scores["occupancy_edge_density"] <= 0.05
    )
    occupied = (
        scores["occupancy_grayscale_std"] >= 0.10 and scores["occupancy_edge_density"] >= 0.10
    )
    if empty:
        return ExtractionStatus.EMPTY, scores
    if occupied:
        return ExtractionStatus.OCCUPIED, scores
    return ExtractionStatus.UNKNOWN, scores


__all__ = ["item_occupancy", "item_occupancy_features"]
