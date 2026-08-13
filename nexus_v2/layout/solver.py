"""Deterministic screen classification and anchor-based geometry registration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray

from nexus_v2.input import DecodedImage, ViewportCandidate, detect_viewports
from nexus_v2.layout.profiles import (
    LoadedProfile,
    PanelDefinition,
    ProfileRegistry,
    RowRelation,
    ScreenType,
    TeamSide,
)
from nexus_v2.schemas.result import ExtractionStatus

ImageArray = NDArray[np.uint8]
Box = tuple[int, int, int, int]
Matrix = tuple[tuple[float, float, float], tuple[float, float, float]]


@dataclass(frozen=True)
class TemplateMatch:
    evidence_id: str
    score: float
    runner_up_score: float
    margin: float
    source_box: Box


@dataclass(frozen=True)
class ScreenClassification:
    status: ExtractionStatus
    screen_type: ScreenType | None
    score: float
    margin: float
    matches: tuple[TemplateMatch, ...]


@dataclass(frozen=True)
class PanelRegistration:
    side: TeamSide
    transform: Matrix
    residual: float
    independently_solved: bool


@dataclass(frozen=True)
class GeometryResult:
    status: ExtractionStatus
    profile_id: str | None
    profile_version: str | None
    viewport: ViewportCandidate | None
    screen: ScreenClassification
    transform: Matrix | None
    panels: tuple[PanelRegistration, ...]
    anchors: tuple[TemplateMatch, ...]
    normalized_residual: float | None
    reasons: tuple[str, ...]


def _map_box(box: tuple[float, float, float, float], matrix: Matrix) -> Box:
    x1, y1, x2, y2 = box
    points = np.asarray(((x1, y1, 1.0), (x2, y2, 1.0)), dtype=np.float64)
    affine = np.asarray(matrix, dtype=np.float64)
    mapped = points @ affine.T
    left = int(round(min(mapped[0, 0], mapped[1, 0])))
    top = int(round(min(mapped[0, 1], mapped[1, 1])))
    right = int(round(max(mapped[0, 0], mapped[1, 0])))
    bottom = int(round(max(mapped[0, 1], mapped[1, 1])))
    return left, top, right, bottom


def _clip_box(box: Box, width: int, height: int) -> Box | None:
    x1, y1, x2, y2 = box
    clipped = max(0, x1), max(0, y1), min(width, x2), min(height, y2)
    return clipped if clipped[2] > clipped[0] and clipped[3] > clipped[1] else None


def _load_gray(path: Path) -> ImageArray:
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError(f"unable to decode profile asset: {path}")
    return np.asarray(image, dtype=np.uint8)


def _runner_up(response: NDArray[np.float32], location: tuple[int, int], radius: int) -> float:
    excluded = response.copy()
    x, y = location
    x1 = max(0, x - radius)
    y1 = max(0, y - radius)
    x2 = min(response.shape[1], x + radius + 1)
    y2 = min(response.shape[0], y + radius + 1)
    excluded[y1:y2, x1:x2] = -1.0
    return float(excluded.max()) if excluded.size else -1.0


def _template_match(
    gray: ImageArray,
    search_box: Box,
    template: ImageArray,
    *,
    evidence_id: str,
    source_scale: tuple[float, float],
) -> TemplateMatch | None:
    clipped = _clip_box(search_box, gray.shape[1], gray.shape[0])
    if clipped is None:
        return None
    x1, y1, x2, y2 = clipped
    search = gray[y1:y2, x1:x2]
    target_width = max(3, int(round(template.shape[1] * source_scale[0])))
    target_height = max(3, int(round(template.shape[0] * source_scale[1])))
    resized = cv2.resize(template, (target_width, target_height), interpolation=cv2.INTER_AREA)
    if search.shape[0] < resized.shape[0] or search.shape[1] < resized.shape[1]:
        return None
    response_raw = cv2.matchTemplate(search, resized, cv2.TM_CCOEFF_NORMED)
    response = np.asarray(response_raw, dtype=np.float32)
    _, best, _, location = cv2.minMaxLoc(response)
    exclusion = max(2, min(resized.shape[:2]) // 4)
    best_location = (int(location[0]), int(location[1]))
    runner = _runner_up(response, best_location, exclusion)
    bx1 = x1 + best_location[0]
    by1 = y1 + best_location[1]
    source_box = bx1, by1, bx1 + resized.shape[1], by1 + resized.shape[0]
    return TemplateMatch(
        evidence_id=evidence_id,
        score=float(np.clip(best, -1.0, 1.0)),
        runner_up_score=float(np.clip(runner, -1.0, 1.0)),
        margin=max(0.0, float(best - runner)),
        source_box=source_box,
    )


def _base_transform(viewport: ViewportCandidate, profile: LoadedProfile) -> Matrix:
    x1, y1, x2, y2 = viewport.box
    canonical = profile.profile.canonical_size
    scale_x = (x2 - x1) / canonical.width
    scale_y = (y2 - y1) / canonical.height
    return ((scale_x, 0.0, float(x1)), (0.0, scale_y, float(y1)))


def _refined_transform(
    base: Matrix,
    profile: LoadedProfile,
    matches: tuple[TemplateMatch, ...],
) -> tuple[Matrix, float]:
    by_id = {match.evidence_id: match for match in matches}
    offsets: list[tuple[float, float]] = []
    residual_scale = float(
        max(profile.profile.canonical_size.width, profile.profile.canonical_size.height)
    )
    for anchor in profile.profile.anchors:
        match = by_id.get(anchor.anchor_id)
        if match is None:
            continue
        expected = _map_box(anchor.canonical_box, base)
        expected_center = ((expected[0] + expected[2]) / 2.0, (expected[1] + expected[3]) / 2.0)
        observed_center = (
            (match.source_box[0] + match.source_box[2]) / 2.0,
            (match.source_box[1] + match.source_box[3]) / 2.0,
        )
        offsets.append(
            (observed_center[0] - expected_center[0], observed_center[1] - expected_center[1])
        )
    if not offsets:
        return base, 1.0
    values = np.asarray(offsets, dtype=np.float64)
    median = np.median(values, axis=0)
    residuals = np.linalg.norm(values - median, axis=1)
    matrix: Matrix = (
        (base[0][0], base[0][1], base[0][2] + float(median[0])),
        (base[1][0], base[1][1], base[1][2] + float(median[1])),
    )
    normalized = float(np.median(residuals) / max(1.0, residual_scale))
    return matrix, normalized


def _classify_screen(
    gray: ImageArray,
    loaded: LoadedProfile,
    matrix: Matrix,
) -> ScreenClassification:
    scale = (matrix[0][0], matrix[1][1])
    matches: list[tuple[ScreenType, TemplateMatch]] = []
    for evidence in loaded.profile.screen_evidence:
        template = _load_gray(loaded.profile.resolve_asset(loaded.path, evidence.template_path))
        target = _map_box(evidence.canonical_box, matrix)
        # Small tolerance absorbs JPEG and viewport-boundary rounding without searching globally.
        tolerance = max(3, int(round(8 * max(scale))))
        search = (
            target[0] - tolerance,
            target[1] - tolerance,
            target[2] + tolerance,
            target[3] + tolerance,
        )
        match = _template_match(
            gray,
            search,
            template,
            evidence_id=evidence.evidence_id,
            source_scale=scale,
        )
        if match is not None:
            matches.append((evidence.screen_type, match))
    all_ordered = sorted(matches, key=lambda item: (-item[1].score, item[0].value))
    if not all_ordered:
        return ScreenClassification(
            status=ExtractionStatus.UNKNOWN,
            screen_type=None,
            score=0.0,
            margin=0.0,
            matches=(),
        )
    best_by_type: dict[ScreenType, TemplateMatch] = {}
    for screen_type, match in all_ordered:
        best_by_type.setdefault(screen_type, match)
    ordered_types = sorted(best_by_type.items(), key=lambda item: (-item[1].score, item[0].value))
    best_type, best = ordered_types[0]
    runner = ordered_types[1][1].score if len(ordered_types) > 1 else -1.0
    margin = max(0.0, best.score - runner)
    status = (
        ExtractionStatus.OK if best.score >= 0.68 and margin >= 0.035 else ExtractionStatus.UNKNOWN
    )
    return ScreenClassification(
        status=status,
        screen_type=best_type if status is ExtractionStatus.OK else None,
        score=best.score,
        margin=margin,
        matches=tuple(match for _, match in all_ordered),
    )


def _refine_panel(
    gray: ImageArray,
    panel: PanelDefinition,
    rows: RowRelation,
    base: Matrix,
) -> PanelRegistration:
    """Refine each panel from its own row separators and center boundary evidence."""

    expected_panel = _map_box(panel.canonical_box, base)
    clipped = _clip_box(expected_panel, gray.shape[1], gray.shape[0])
    if clipped is None:
        return PanelRegistration(
            side=panel.side,
            transform=base,
            residual=1.0,
            independently_solved=False,
        )
    x1, y1, x2, y2 = clipped
    panel_gray = gray[y1:y2, x1:x2].astype(np.float32)
    y_response = np.mean(np.abs(np.diff(panel_gray, axis=0)), axis=1)
    source_radius_y = max(2, int(round(min(rows.search_radius, 6.0) * base[1][1])))
    observed_y_offsets: list[float] = []
    for index in range(rows.count + 1):
        canonical_y = rows.first_top + index * rows.step
        expected_y = int(round(base[1][1] * canonical_y + base[1][2]))
        local_expected = expected_y - y1
        low = max(0, local_expected - source_radius_y)
        high = min(y_response.size, local_expected + source_radius_y + 1)
        if high <= low:
            continue
        observed = low + int(np.argmax(y_response[low:high])) + y1
        observed_y_offsets.append(float(observed - expected_y))

    # The shared center divider is measured from each side's own pixels rather than mirrored.
    center_x = expected_panel[2] if panel.side is TeamSide.ALLY else expected_panel[0]
    source_radius_x = max(2, int(round(panel.edge_search_radius * base[0][0])))
    low_x = max(1, center_x - source_radius_x)
    high_x = min(gray.shape[1] - 1, center_x + source_radius_x + 1)
    panel_top = max(0, expected_panel[1])
    panel_bottom = min(gray.shape[0], expected_panel[3])
    x_offset = 0.0
    if high_x > low_x and panel_bottom > panel_top:
        x_strip = gray[panel_top:panel_bottom, low_x - 1 : high_x + 1].astype(np.float32)
        x_response = np.mean(np.abs(np.diff(x_strip, axis=1)), axis=0)
        observed_x = low_x + int(np.argmax(x_response))
        x_offset = float(observed_x - center_x)

    y_offset = float(np.median(observed_y_offsets)) if observed_y_offsets else 0.0
    residual_values = (
        np.abs(np.asarray(observed_y_offsets, dtype=np.float64) - y_offset)
        if observed_y_offsets
        else np.asarray((rows.height,), dtype=np.float64)
    )
    residual = float(np.median(residual_values) / max(1.0, rows.height * base[1][1]))
    if abs(x_offset) <= 1.5:
        x_offset = 0.0
    if abs(y_offset) <= 1.5:
        y_offset = 0.0
    elif abs(y_offset) > 4.0 or residual > 0.03:
        # Conflicting row content must not drag otherwise accepted panel geometry.
        y_offset = 0.0
    transform: Matrix = (
        (base[0][0], base[0][1], base[0][2] + x_offset),
        (base[1][0], base[1][1], base[1][2] + y_offset),
    )
    return PanelRegistration(
        side=panel.side,
        transform=transform,
        residual=residual,
        independently_solved=bool(observed_y_offsets),
    )


def solve_geometry(
    image: DecodedImage,
    registry: ProfileRegistry,
    *,
    max_viewports: int = 8,
) -> GeometryResult:
    """Solve a verified profile without global screenshot resizing or mirrored panels."""

    runtime = registry.runtime_profiles
    if not runtime:
        return GeometryResult(
            status=ExtractionStatus.UNSUPPORTED_LAYOUT,
            profile_id=None,
            profile_version=None,
            viewport=None,
            screen=ScreenClassification(
                status=ExtractionStatus.UNKNOWN,
                screen_type=None,
                score=0.0,
                margin=0.0,
                matches=(),
            ),
            transform=None,
            panels=(),
            anchors=(),
            normalized_residual=None,
            reasons=("no_verified_runtime_profile",),
        )
    aspects = tuple(profile.profile.canonical_size.aspect_ratio for profile in runtime)
    viewports = detect_viewports(image, target_aspects=aspects, max_candidates=max_viewports)
    gray = np.asarray(cv2.cvtColor(image.rgb, cv2.COLOR_RGB2GRAY), dtype=np.uint8)
    candidates: list[tuple[float, GeometryResult]] = []
    for loaded in runtime:
        profile = loaded.profile
        for viewport in viewports:
            if viewport.aspect_error > profile.compatibility.allowed_aspect_error:
                continue
            base = _base_transform(viewport, loaded)
            scale = (base[0][0], base[1][1])
            anchor_matches: list[TemplateMatch] = []
            accepted_families: set[str] = set()
            for anchor in profile.anchors:
                template = _load_gray(profile.resolve_asset(loaded.path, anchor.template_path))
                search = _map_box(anchor.search_box, base)
                match = _template_match(
                    gray,
                    search,
                    template,
                    evidence_id=anchor.anchor_id,
                    source_scale=scale,
                )
                if match is None:
                    continue
                anchor_matches.append(match)
                if match.score >= anchor.minimum_score and match.margin >= anchor.minimum_margin:
                    accepted_families.add(anchor.family.value)
            accepted = tuple(
                match
                for match in anchor_matches
                if any(
                    anchor.anchor_id == match.evidence_id
                    and match.score >= anchor.minimum_score
                    and match.margin >= anchor.minimum_margin
                    for anchor in profile.anchors
                )
            )
            transform, residual = _refined_transform(base, loaded, accepted)
            screen = _classify_screen(gray, loaded, transform)
            reasons: list[str] = []
            if len(accepted_families) < 2:
                reasons.append("insufficient_independent_anchor_families")
            if residual > 0.012:
                reasons.append("anchor_residual_too_large")
            if screen.status is not ExtractionStatus.OK:
                reasons.append("screen_type_not_separated")
            status = ExtractionStatus.OK if not reasons else ExtractionStatus.UNSUPPORTED_LAYOUT
            panels = tuple(
                _refine_panel(gray, panel, profile.row_relation, transform)
                for panel in profile.panels
            )
            if any(not panel.independently_solved for panel in panels):
                reasons.append("panel_registration_missing")
                status = ExtractionStatus.UNSUPPORTED_LAYOUT
            mean_anchor = float(np.mean([match.score for match in accepted])) if accepted else 0.0
            combined = 0.30 * viewport.score + 0.42 * mean_anchor + 0.28 * screen.score
            candidates.append(
                (
                    combined,
                    GeometryResult(
                        status=status,
                        profile_id=profile.profile_id,
                        profile_version=profile.profile_version,
                        viewport=viewport,
                        screen=screen,
                        transform=transform,
                        panels=panels,
                        anchors=tuple(anchor_matches),
                        normalized_residual=residual,
                        reasons=tuple(reasons),
                    ),
                )
            )
    if not candidates:
        return GeometryResult(
            status=ExtractionStatus.UNSUPPORTED_LAYOUT,
            profile_id=None,
            profile_version=None,
            viewport=None,
            screen=ScreenClassification(
                status=ExtractionStatus.UNKNOWN,
                screen_type=None,
                score=0.0,
                margin=0.0,
                matches=(),
            ),
            transform=None,
            panels=(),
            anchors=(),
            normalized_residual=None,
            reasons=("no_profile_viewport_hypothesis",),
        )
    return max(candidates, key=lambda item: (item[0], item[1].profile_id or ""))[1]


__all__ = [
    "GeometryResult",
    "Matrix",
    "PanelRegistration",
    "ScreenClassification",
    "TemplateMatch",
    "solve_geometry",
]
