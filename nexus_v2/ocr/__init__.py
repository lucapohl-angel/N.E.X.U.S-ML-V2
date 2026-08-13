"""Offline-first OCR with semantic validation and honest abstention."""

from nexus_v2.ocr.local import RapidOCRBackend, TesseractBackend
from nexus_v2.ocr.normalize import ParsedOCR, parse_ocr
from nexus_v2.ocr.pipeline import LocalOCRPipeline
from nexus_v2.ocr.types import OCRBackend, OCRCandidate

__all__ = [
    "LocalOCRPipeline",
    "OCRBackend",
    "OCRCandidate",
    "ParsedOCR",
    "RapidOCRBackend",
    "TesseractBackend",
    "parse_ocr",
]
