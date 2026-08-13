"""Deterministic screenshot-quality features used for routing and abstention."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from numpy.typing import NDArray

from nexus_v2.input.decoder import DecodedImage
from nexus_v2.schemas.result import ExtractionStatus


@dataclass(frozen=True)
class ImageQuality:
    status: ExtractionStatus
    blur_variance: float
    blur_score: float
    compression_artifact_score: float
    compression_quality_score: float
    clipping_fraction: float
    edge_density: float
    dynamic_range: int
    suspected_rescaling: bool
    screenshot_validity_score: float
    effective_icon_resolution: float
    native_width: int
    native_height: int
    reasons: tuple[str, ...]


def _blockiness(gray: NDArray[np.uint8]) -> float:
    if gray.shape[0] < 16 or gray.shape[1] < 16:
        return 1.0
    values = gray.astype(np.float32)
    vertical = np.abs(np.diff(values, axis=1))
    horizontal = np.abs(np.diff(values, axis=0))
    boundary_v = float(vertical[:, 7::8].mean()) if vertical[:, 7::8].size else 0.0
    boundary_h = float(horizontal[7::8, :].mean()) if horizontal[7::8, :].size else 0.0
    interior_v = float(np.delete(vertical, np.s_[7::8], axis=1).mean())
    interior_h = float(np.delete(horizontal, np.s_[7::8], axis=0).mean())
    excess = max(0.0, (boundary_v + boundary_h) - (interior_v + interior_h))
    return min(1.0, excess / 24.0)


def analyze_quality(image: DecodedImage) -> ImageQuality:
    """Measure quality without modifying or replacing the decoded native pixels."""

    gray: NDArray[np.uint8] = np.asarray(
        cv2.cvtColor(image.rgb, cv2.COLOR_RGB2GRAY), dtype=np.uint8
    )
    blur_variance = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    blur_score = min(1.0, blur_variance / 180.0)
    compression_artifacts = _blockiness(gray)
    compression_quality = 1.0 - compression_artifacts
    edges = cv2.Canny(gray, 45, 135)
    edge_density = float(np.count_nonzero(edges) / edges.size)
    gray_values: NDArray[np.float64] = gray.astype(np.float64)
    p01, p99 = np.percentile(gray_values, (1, 99))
    dynamic_range = int(round(float(p99 - p01)))
    clipped = np.count_nonzero((gray <= 2) | (gray >= 253))
    clipping_fraction = float(clipped / gray.size)

    # Repeated adjacent pixels in both axes are a conservative rescaling signal. JPEG alone can
    # create some repeats, hence the deliberately high threshold.
    equal_x = float(np.mean(gray[:, 1:] == gray[:, :-1])) if image.width > 1 else 1.0
    equal_y = float(np.mean(gray[1:, :] == gray[:-1, :])) if image.height > 1 else 1.0
    suspected_rescaling = equal_x > 0.42 and equal_y > 0.42
    content_score = min(1.0, edge_density / 0.035)
    range_score = min(1.0, dynamic_range / 110.0)
    validity = float(
        np.clip(
            0.30 * blur_score
            + 0.25 * compression_quality
            + 0.25 * content_score
            + 0.20 * range_score,
            0.0,
            1.0,
        )
    )
    effective_icon_resolution = min(image.width / 1600.0, image.height / 900.0) * 48.0

    reasons: list[str] = []
    if blur_variance < 18.0:
        reasons.append("severe_blur")
    if compression_artifacts > 0.75:
        reasons.append("severe_block_compression")
    if dynamic_range < 20:
        reasons.append("insufficient_dynamic_range")
    if edge_density < 0.003:
        reasons.append("insufficient_structural_edges")
    if min(image.width, image.height) < 240:
        reasons.append("insufficient_native_resolution")
    status = ExtractionStatus.LOW_QUALITY if reasons or validity < 0.28 else ExtractionStatus.OK
    return ImageQuality(
        status=status,
        blur_variance=blur_variance,
        blur_score=blur_score,
        compression_artifact_score=compression_artifacts,
        compression_quality_score=compression_quality,
        clipping_fraction=clipping_fraction,
        edge_density=edge_density,
        dynamic_range=dynamic_range,
        suspected_rescaling=suspected_rescaling,
        screenshot_validity_score=validity,
        effective_icon_resolution=effective_icon_resolution,
        native_width=image.width,
        native_height=image.height,
        reasons=tuple(reasons),
    )
