"""Field-aware OCR preprocessing that never modifies the source screenshot."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class OCRVariant:
    name: str
    image: NDArray[np.uint8]


def _scale(image: NDArray[np.uint8], factor: int = 3) -> NDArray[np.uint8]:
    return np.asarray(
        cv2.resize(
            image,
            (image.shape[1] * factor, image.shape[0] * factor),
            interpolation=cv2.INTER_CUBIC,
        ),
        dtype=np.uint8,
    )


def _gray(image: NDArray[np.uint8]) -> NDArray[np.uint8]:
    if image.ndim == 2:
        return np.ascontiguousarray(image)
    return np.asarray(cv2.cvtColor(image, cv2.COLOR_RGB2GRAY), dtype=np.uint8)


def build_ocr_variants(
    image: NDArray[np.uint8],
    *,
    parser: str,
) -> tuple[OCRVariant, ...]:
    """Return deterministic variants ordered from least to most destructive."""

    if image.size == 0:
        return ()
    variants: list[OCRVariant] = [OCRVariant(name="native", image=np.ascontiguousarray(image))]
    scaled = _scale(image)
    variants.append(OCRVariant(name="cubic3x", image=scaled))
    gray = _gray(scaled)
    if parser == "player_name":
        variants.append(OCRVariant(name="gray3x", image=gray))
        return tuple(variants)

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4)).apply(gray)
    variants.append(OCRVariant(name="clahe3x", image=np.asarray(clahe, dtype=np.uint8)))
    _, otsu = cv2.threshold(clahe, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants.append(OCRVariant(name="otsu3x", image=np.asarray(otsu, dtype=np.uint8)))
    variants.append(
        OCRVariant(name="otsu3x_inverted", image=np.asarray(255 - otsu, dtype=np.uint8))
    )
    if parser == "level":
        hsv = cv2.cvtColor(scaled, cv2.COLOR_RGB2HSV)
        white_glyph = cv2.inRange(
            hsv,
            np.asarray((0, 0, 140), dtype=np.uint8),
            np.asarray((179, 110, 255), dtype=np.uint8),
        )
        white_glyph = cv2.morphologyEx(
            white_glyph,
            cv2.MORPH_CLOSE,
            np.ones((2, 2), dtype=np.uint8),
        )
        variants.append(
            OCRVariant(name="white_glyph3x", image=np.asarray(white_glyph, dtype=np.uint8))
        )
        variants.append(
            OCRVariant(
                name="white_glyph3x_inverted",
                image=np.asarray(255 - white_glyph, dtype=np.uint8),
            )
        )
    return tuple(variants)


__all__ = ["OCRVariant", "build_ocr_variants"]
