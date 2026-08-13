"""Native-pixel semantic crops produced from accepted geometry only."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from numpy.typing import NDArray

from nexus_v2.input import DecodedImage
from nexus_v2.layout.item_slots import item_occupancy
from nexus_v2.layout.profiles import (
    FieldKind,
    LoadedProfile,
    ScreenType,
    SemanticFieldDefinition,
    TeamSide,
)
from nexus_v2.layout.solver import GeometryResult, Matrix
from nexus_v2.schemas.result import ExtractionStatus

ImageArray = NDArray[np.uint8]
Box = tuple[int, int, int, int]


@dataclass(frozen=True)
class SemanticCrop:
    field_id: str
    kind: FieldKind
    screen_type: ScreenType
    side: TeamSide | None
    row: int | None
    slot: int | None
    parser: str | None
    tight_box: Box
    context_box: Box
    tight_rgb: ImageArray
    context_rgb: ImageArray
    mask: NDArray[np.uint8] | None
    clipped: bool


def _map_box(box: tuple[float, float, float, float], matrix: Matrix) -> Box:
    x1, y1, x2, y2 = box
    left = int(round(matrix[0][0] * x1 + matrix[0][1] * y1 + matrix[0][2]))
    top = int(round(matrix[1][0] * x1 + matrix[1][1] * y1 + matrix[1][2]))
    right = int(round(matrix[0][0] * x2 + matrix[0][1] * y2 + matrix[0][2]))
    bottom = int(round(matrix[1][0] * x2 + matrix[1][1] * y2 + matrix[1][2]))
    return min(left, right), min(top, bottom), max(left, right), max(top, bottom)


def _clip(box: Box, width: int, height: int) -> tuple[Box, bool] | None:
    x1, y1, x2, y2 = box
    clipped = max(0, x1), max(0, y1), min(width, x2), min(height, y2)
    if clipped[2] <= clipped[0] or clipped[3] <= clipped[1]:
        return None
    return clipped, clipped != box


def _canonical_instance(
    field: SemanticFieldDefinition,
    row: int | None,
    slot: int | None,
    padding: float,
) -> tuple[float, float, float, float]:
    x1, y1, x2, y2 = field.canonical_box
    if row is not None:
        y1 += row * field.row_step
        y2 += row * field.row_step
    if slot is not None:
        x1 += slot * field.slot_step
        x2 += slot * field.slot_step
    return x1 - padding, y1 - padding, x2 + padding, y2 + padding


def _ellipse_mask(width: int, height: int) -> NDArray[np.uint8]:
    mask = np.zeros((height, width), dtype=np.uint8)
    center = (max(0, (width - 1) // 2), max(0, (height - 1) // 2))
    axes = (max(1, width // 2 - 1), max(1, height // 2 - 1))
    cv2.ellipse(mask, center, axes, 0.0, 0.0, 360.0, 255, thickness=-1)
    return mask


def _slot_instances(
    image: DecodedImage,
    field: SemanticFieldDefinition,
    row: int | None,
    transform: Matrix,
    count: int,
) -> tuple[tuple[int, int], ...]:
    regular = tuple((slot, slot) for slot in range(count))
    if field.kind is not FieldKind.ITEM or field.side is None or row is None:
        return regular

    # Flower of Hope creates a seventh visible item. The ally table appends it
    # after the normal six; the enemy table shifts the seven-icon group left.
    candidate_slot = count if field.side is TeamSide.ALLY else -1
    requested = _map_box(
        _canonical_instance(field, row, candidate_slot, field.tight_padding), transform
    )
    clipped = _clip(requested, image.width, image.height)
    if clipped is None:
        return regular
    (x1, y1, x2, y2), was_clipped = clipped
    if was_clipped:
        return regular
    candidate_rgb = np.ascontiguousarray(image.rgb[y1:y2, x1:x2].copy())
    occupancy, _ = item_occupancy(candidate_rgb)
    if occupancy is not ExtractionStatus.OCCUPIED:
        return regular
    if field.side is TeamSide.ALLY:
        return tuple((slot, slot) for slot in range(count + 1))
    return tuple(
        (semantic_slot, physical_slot)
        for semantic_slot, physical_slot in enumerate(range(-1, count))
    )


def build_semantic_crops(
    image: DecodedImage,
    loaded: LoadedProfile,
    geometry: GeometryResult,
) -> tuple[SemanticCrop, ...]:
    """Crop only after accepted registration; never resize the full screenshot."""

    if geometry.status is not ExtractionStatus.OK:
        raise ValueError("semantic crops require accepted geometry")
    if geometry.transform is None or geometry.screen.screen_type is None:
        raise ValueError("accepted geometry is missing its transform or screen type")
    if geometry.profile_id != loaded.profile.profile_id:
        raise ValueError("geometry/profile ID mismatch")
    screen_type = geometry.screen.screen_type
    panel_transforms = {panel.side: panel.transform for panel in geometry.panels}
    crops: list[SemanticCrop] = []
    for field in loaded.profile.fields:
        if screen_type not in field.screen_types:
            continue
        transform = geometry.transform
        if field.side is not None:
            panel_transform = panel_transforms.get(field.side)
            if panel_transform is None:
                raise ValueError(f"missing independent {field.side.value} panel transform")
            transform = panel_transform
        rows: tuple[int | None, ...] = (
            tuple(range(loaded.profile.row_relation.count)) if field.row_repeat else (None,)
        )
        for row in rows:
            slot_instances: tuple[tuple[int | None, int | None], ...] = (
                _slot_instances(
                    image,
                    field,
                    row,
                    transform,
                    loaded.profile.slot_relation.count,
                )
                if field.slot_repeat
                else ((None, None),)
            )
            for slot, canonical_slot in slot_instances:
                tight_requested = _map_box(
                    _canonical_instance(field, row, canonical_slot, field.tight_padding), transform
                )
                context_requested = _map_box(
                    _canonical_instance(field, row, canonical_slot, field.context_padding),
                    transform,
                )
                tight_result = _clip(tight_requested, image.width, image.height)
                context_result = _clip(context_requested, image.width, image.height)
                if tight_result is None or context_result is None:
                    continue
                tight_box, tight_clipped = tight_result
                context_box, context_clipped = context_result
                tx1, ty1, tx2, ty2 = tight_box
                cx1, cy1, cx2, cy2 = context_box
                tight_rgb = np.ascontiguousarray(image.rgb[ty1:ty2, tx1:tx2].copy())
                context_rgb = np.ascontiguousarray(image.rgb[cy1:cy2, cx1:cx2].copy())
                mask = (
                    _ellipse_mask(tight_rgb.shape[1], tight_rgb.shape[0])
                    if field.mask_shape == "ellipse"
                    else None
                )
                crops.append(
                    SemanticCrop(
                        field_id=field.field_id,
                        kind=field.kind,
                        screen_type=screen_type,
                        side=field.side,
                        row=row,
                        slot=slot,
                        parser=field.parser,
                        tight_box=tight_box,
                        context_box=context_box,
                        tight_rgb=tight_rgb,
                        context_rgb=context_rgb,
                        mask=mask,
                        clipped=tight_clipped or context_clipped,
                    )
                )
    return tuple(
        sorted(
            crops,
            key=lambda crop: (
                crop.kind.value,
                crop.field_id,
                crop.side.value if crop.side else "",
                crop.row if crop.row is not None else -1,
                crop.slot if crop.slot is not None else -1,
            ),
        )
    )


__all__ = ["SemanticCrop", "build_semantic_crops"]
