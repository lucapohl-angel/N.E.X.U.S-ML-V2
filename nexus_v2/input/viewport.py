"""Ranked viewport hypotheses for bars, canvas padding, and cropped captures."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import cv2
import numpy as np
from numpy.typing import NDArray

from nexus_v2.input.decoder import DecodedImage

Box = tuple[int, int, int, int]


class PaddingKind(str, Enum):
    NONE = "none"
    BLACK = "black"
    WHITE = "white"
    DISCORD_LIKE = "discord_like"
    UNIFORM_COLOR = "uniform_color"
    MIXED = "mixed"


@dataclass(frozen=True)
class ViewportCandidate:
    box: Box
    score: float
    aspect_ratio: float
    target_aspect_ratio: float
    aspect_error: float
    padding: PaddingKind
    padding_fraction: float
    clipped_edges: tuple[str, ...]
    edge_transition_score: float
    content_contrast_score: float
    source: str


ImageArray = NDArray[np.uint8]


def _padding_pixels(rgb: ImageArray, box: Box) -> ImageArray:
    height, width = rgb.shape[:2]
    x1, y1, x2, y2 = box
    pieces = [
        rgb[:y1, :, :].reshape(-1, 3),
        rgb[y2:height, :, :].reshape(-1, 3),
        rgb[y1:y2, :x1, :].reshape(-1, 3),
        rgb[y1:y2, x2:width, :].reshape(-1, 3),
    ]
    nonempty = [piece for piece in pieces if piece.size]
    return np.concatenate(nonempty, axis=0) if nonempty else np.empty((0, 3), dtype=np.uint8)


def _classify_padding(rgb: ImageArray, box: Box) -> PaddingKind:
    pixels = _padding_pixels(rgb, box)
    if not pixels.size:
        return PaddingKind.NONE
    mean = float(pixels.mean())
    deviation = float(pixels.std())
    channel_spread = float(np.max(pixels.mean(axis=0)) - np.min(pixels.mean(axis=0)))
    if mean < 12.0 and deviation < 18.0:
        return PaddingKind.BLACK
    if mean > 243.0 and deviation < 18.0:
        return PaddingKind.WHITE
    if deviation < 8.0:
        return PaddingKind.UNIFORM_COLOR
    if mean < 85.0 and channel_spread < 28.0:
        return PaddingKind.DISCORD_LIKE
    return PaddingKind.MIXED


def _candidate_score(
    rgb: ImageArray, box: Box, target_aspect: float, transition: float, source: str
) -> ViewportCandidate:
    height, width = rgb.shape[:2]
    x1, y1, x2, y2 = box
    candidate_width = max(1, x2 - x1)
    candidate_height = max(1, y2 - y1)
    aspect = candidate_width / candidate_height
    aspect_error = abs(aspect - target_aspect) / target_aspect
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    inside = gray[y1:y2, x1:x2]
    padding = _padding_pixels(rgb, box)
    inside_edges = cv2.Canny(inside, 40, 120)
    inside_density = float(np.count_nonzero(inside_edges) / max(1, inside_edges.size))
    if padding.size:
        padding_gray = cv2.cvtColor(padding.reshape(1, -1, 3), cv2.COLOR_RGB2GRAY)
        padding_mean = float(padding_gray.mean())
        inside_mean = float(inside.mean())
        luminance_separation = min(1.0, abs(inside_mean - padding_mean) / 70.0)
        texture_separation = min(1.0, max(0.0, inside_density - 0.01) / 0.06)
        contrast = 0.45 * luminance_separation + 0.55 * texture_separation
    else:
        contrast = min(1.0, inside_density / 0.06)
    padding_fraction = 1.0 - (candidate_width * candidate_height) / (width * height)
    padding_kind = _classify_padding(rgb, box)
    padding_support = (
        0.65
        if padding_kind
        in {
            PaddingKind.BLACK,
            PaddingKind.WHITE,
            PaddingKind.DISCORD_LIKE,
            PaddingKind.UNIFORM_COLOR,
        }
        else 0.25
    )
    if padding_kind is PaddingKind.NONE:
        padding_support = 0.45
    score = float(
        np.clip(
            0.38 * (1.0 - min(1.0, aspect_error * 8.0))
            + 0.30 * min(1.0, transition)
            + 0.20 * contrast
            + 0.12 * padding_support,
            0.0,
            1.0,
        )
    )
    clipped: list[str] = []
    if source == "cropped_full_frame":
        if aspect < target_aspect:
            clipped.extend(("left", "right"))
        else:
            clipped.extend(("top", "bottom"))
    return ViewportCandidate(
        box=box,
        score=score,
        aspect_ratio=aspect,
        target_aspect_ratio=target_aspect,
        aspect_error=aspect_error,
        padding=padding_kind,
        padding_fraction=padding_fraction,
        clipped_edges=tuple(clipped),
        edge_transition_score=min(1.0, transition),
        content_contrast_score=contrast,
        source=source,
    )


def _unique_candidates(candidates: list[ViewportCandidate]) -> tuple[ViewportCandidate, ...]:
    best_by_box: dict[Box, ViewportCandidate] = {}
    for candidate in candidates:
        previous = best_by_box.get(candidate.box)
        if previous is None or candidate.score > previous.score:
            best_by_box[candidate.box] = candidate
    return tuple(sorted(best_by_box.values(), key=lambda item: (-item.score, item.box)))


def detect_viewports(
    image: DecodedImage,
    *,
    target_aspects: tuple[float, ...] = (16.0 / 9.0,),
    max_candidates: int = 8,
) -> tuple[ViewportCandidate, ...]:
    """Return deterministic ranked viewport rectangles without selecting by resolution."""

    if not target_aspects or max_candidates <= 0:
        raise ValueError("at least one target aspect and a positive max_candidates are required")
    rgb = image.rgb
    height, width = rgb.shape[:2]
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    row_delta = np.mean(np.abs(np.diff(gray, axis=0)), axis=1) if height > 1 else np.zeros(1)
    col_delta = np.mean(np.abs(np.diff(gray, axis=1)), axis=0) if width > 1 else np.zeros(1)
    row_scale = max(1.0, float(np.percentile(row_delta, 95)))
    col_scale = max(1.0, float(np.percentile(col_delta, 95)))
    candidates: list[ViewportCandidate] = []

    for target in target_aspects:
        if target <= 0:
            raise ValueError("target aspect ratios must be positive")
        expected_height = int(round(width / target))
        if expected_height <= height:
            centered_top = (height - expected_height) // 2
            top_options = {0, height - expected_height, centered_top}
            strongest_rows = (
                np.argsort(row_delta)[-20:] if row_delta.size else np.array([], dtype=int)
            )
            for boundary in strongest_rows:
                top_options.add(int(boundary) + 1)
                top_options.add(int(boundary) - expected_height + 1)
            for top in sorted(top_options):
                bottom = top + expected_height
                if top < 0 or bottom > height:
                    continue
                top_transition = float(row_delta[top - 1] / row_scale) if top > 0 else 0.35
                bottom_transition = (
                    float(row_delta[bottom - 1] / row_scale) if bottom < height else 0.35
                )
                transition = (top_transition + bottom_transition) / 2.0
                candidates.append(
                    _candidate_score(
                        rgb,
                        (0, top, width, bottom),
                        target,
                        transition,
                        "aspect_boundary",
                    )
                )

        expected_width = int(round(height * target))
        if expected_width <= width:
            centered_left = (width - expected_width) // 2
            left_options = {0, width - expected_width, centered_left}
            strongest_columns = (
                np.argsort(col_delta)[-20:] if col_delta.size else np.array([], dtype=int)
            )
            for boundary in strongest_columns:
                left_options.add(int(boundary) + 1)
                left_options.add(int(boundary) - expected_width + 1)
            for left in sorted(left_options):
                right = left + expected_width
                if left < 0 or right > width:
                    continue
                left_transition = float(col_delta[left - 1] / col_scale) if left > 0 else 0.35
                right_transition = (
                    float(col_delta[right - 1] / col_scale) if right < width else 0.35
                )
                transition = (left_transition + right_transition) / 2.0
                candidates.append(
                    _candidate_score(
                        rgb,
                        (left, 0, right, height),
                        target,
                        transition,
                        "aspect_boundary",
                    )
                )

        full_aspect = width / height
        source = (
            "full_frame" if abs(full_aspect - target) / target <= 0.035 else "cropped_full_frame"
        )
        candidates.append(_candidate_score(rgb, (0, 0, width, height), target, 0.35, source))

    return _unique_candidates(candidates)[:max_candidates]
