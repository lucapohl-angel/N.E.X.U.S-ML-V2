"""Offline OCR backends. RapidOCR is optional; Tesseract remains portable."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from importlib import import_module
from typing import Any, Protocol, cast

import cv2
import numpy as np
import pytesseract  # type: ignore[import-untyped]
from numpy.typing import NDArray

from nexus_v2.ocr.types import OCRCandidate


class _RapidEngine(Protocol):
    def __call__(
        self,
        image: NDArray[np.uint8],
        *,
        use_det: bool,
        use_cls: bool,
        use_rec: bool,
    ) -> object: ...


def _joined_confidence(parts: Sequence[tuple[str, float]]) -> float:
    total = sum(max(1, len(text)) for text, _ in parts)
    if total == 0:
        return 0.0
    return float(
        np.clip(
            sum(max(1, len(text)) * confidence for text, confidence in parts) / total,
            0.0,
            1.0,
        )
    )


class RapidOCRBackend:
    """Thin adapter that does not force a heavyweight optional dependency."""

    name = "rapidocr-onnxruntime"

    def __init__(
        self,
        *,
        text_detection: bool = True,
        use_cuda: bool = False,
        intra_op_num_threads: int | None = None,
        inter_op_num_threads: int | None = None,
    ) -> None:
        try:
            module = import_module("rapidocr_onnxruntime")
        except ImportError as exc:
            raise RuntimeError(
                "RapidOCR is not installed; install rapidocr-onnxruntime==1.4.4"
            ) from exc
        factory = cast(Callable[..., _RapidEngine], module.RapidOCR)
        kwargs: dict[str, object] = {"use_cuda": use_cuda}
        if intra_op_num_threads is not None:
            kwargs["intra_op_num_threads"] = intra_op_num_threads
        if inter_op_num_threads is not None:
            kwargs["inter_op_num_threads"] = inter_op_num_threads
        self._engine = factory(**kwargs)
        self.text_detection = text_detection
        self.use_cuda = use_cuda

    def recognize(self, image: NDArray[np.uint8], *, parser: str) -> OCRCandidate | None:
        prepared = image
        if image.ndim == 3:
            prepared = np.asarray(cv2.cvtColor(image, cv2.COLOR_RGB2BGR), dtype=np.uint8)
        use_detection = self.text_detection and parser in {
            "battle_id",
            "battle_id_18",
            "datetime",
        }
        output = self._engine(
            prepared,
            use_det=use_detection,
            use_cls=False,
            use_rec=True,
        )
        if not isinstance(output, tuple) or not output:
            return None
        records = output[0]
        if not isinstance(records, list):
            return None
        parts: list[tuple[float, str, float]] = []
        for record in records:
            if not isinstance(record, list | tuple) or len(record) < 2:
                continue
            if len(record) == 2:
                text, raw_confidence = record[0], record[1]
                box = None
            else:
                text, raw_confidence = record[1], record[2]
                box = record[0]
            if not isinstance(text, str) or not isinstance(raw_confidence, int | float):
                continue
            left = 0.0
            if isinstance(box, list | tuple) and box:
                point = box[0]
                if isinstance(point, list | tuple) and point and isinstance(point[0], int | float):
                    left = float(point[0])
            clean = text.strip()
            if clean:
                parts.append((left, clean, float(raw_confidence)))
        if not parts:
            return None
        ordered = sorted(parts, key=lambda part: part[0])
        text_confidence = [(text, confidence) for _, text, confidence in ordered]
        return OCRCandidate(
            raw=" ".join(text for text, _ in text_confidence),
            confidence=_joined_confidence(text_confidence),
            backend=self.name,
            preprocessing="backend_input",
        )


class TesseractBackend:
    name = "tesseract"

    def __init__(self, *, language: str = "eng", timeout_seconds: int = 3) -> None:
        self.language = language
        self.timeout_seconds = timeout_seconds

    def recognize(self, image: NDArray[np.uint8], *, parser: str) -> OCRCandidate | None:
        config = "--oem 3 --psm 7"
        if parser in {
            "battle_id",
            "battle_id_18",
            "level",
            "short_integer",
            "small_integer",
            "large_integer",
            "percentage",
        }:
            config += " -c tessedit_char_whitelist=0123456789%"
        elif parser == "decimal":
            config += " -c tessedit_char_whitelist=0123456789.,"
        elif parser == "duration":
            config += " -c tessedit_char_whitelist=0123456789:."
        elif parser == "datetime":
            config += " -c tessedit_char_whitelist=0123456789/:-."
        try:
            data: dict[str, list[Any]] = pytesseract.image_to_data(
                image,
                lang=self.language,
                config=config,
                timeout=self.timeout_seconds,
                output_type=pytesseract.Output.DICT,
            )
        except (pytesseract.TesseractError, RuntimeError):
            return None
        parts: list[tuple[str, float]] = []
        for text, raw_confidence in zip(data.get("text", []), data.get("conf", []), strict=False):
            clean = str(text).strip()
            try:
                confidence = float(raw_confidence) / 100.0
            except (TypeError, ValueError):
                continue
            if clean and confidence >= 0.0:
                parts.append((clean, confidence))
        if not parts:
            return None
        return OCRCandidate(
            raw=" ".join(text for text, _ in parts),
            confidence=_joined_confidence(parts),
            backend=self.name,
            preprocessing="backend_input",
        )


__all__ = ["RapidOCRBackend", "TesseractBackend"]
