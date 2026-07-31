from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from nexus_v2.schemas.annotation import ApprovalStatus, BenchmarkSample, SourceMetadata
from nexus_v2.schemas.result import (
    ConfidenceSemantics,
    ExtractedField,
    ExtractionStatus,
)


def test_extraction_status_covers_every_prd_state() -> None:
    assert {status.value for status in ExtractionStatus} == {
        "ok",
        "unknown",
        "invalid_crop",
        "low_quality",
        "validation_failed",
        "invalid_image",
        "unsupported_layout",
        "unsupported",
        "conflict",
        "empty",
        "occupied",
    }


def test_true_zero_is_valid_and_distinct_from_unknown() -> None:
    zero = ExtractedField(
        raw="0",
        value=0,
        status=ExtractionStatus.OK,
        confidence=0.9,
        confidence_semantics=ConfidenceSemantics.OCR_SEQUENCE,
    )
    missing = ExtractedField(raw=None, value=None, status=ExtractionStatus.UNKNOWN)

    assert zero.value == 0
    assert missing.value is None
    assert zero.status is not missing.status


def test_confidence_requires_declared_semantics() -> None:
    with pytest.raises(ValidationError, match="confidence_semantics"):
        ExtractedField(raw="12", value=12, status=ExtractionStatus.OK, confidence=0.9)


def test_approved_sample_requires_review_evidence_and_annotation() -> None:
    with pytest.raises(ValidationError, match="approved sample is missing"):
        BenchmarkSample(
            sample_id="shot-1",
            match_group_id="match-1",
            image_path="shot.png",
            sha256="0" * 64,
            approval=ApprovalStatus.APPROVED,
            reviewed_at=datetime.now(timezone.utc),
            source=SourceMetadata(width=1920, height=1080),
        )
