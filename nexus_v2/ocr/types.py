"""Local OCR contracts with explicit backend and preprocessing provenance."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class OCRCandidate:
    raw: str
    confidence: float
    backend: str
    preprocessing: str


class OCRBackend(Protocol):
    name: str

    def recognize(self, image: NDArray[np.uint8], *, parser: str) -> OCRCandidate | None: ...


__all__ = ["OCRBackend", "OCRCandidate"]
