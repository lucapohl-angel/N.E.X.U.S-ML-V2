"""Pydantic v2 schemas for versioned extraction results."""

from __future__ import annotations

from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing_extensions import Self


class ExtractionStatus(str, Enum):
    """Every success, abstention, and failure status required by the V2 PRD."""

    OK = "ok"
    UNKNOWN = "unknown"
    INVALID_CROP = "invalid_crop"
    LOW_QUALITY = "low_quality"
    VALIDATION_FAILED = "validation_failed"
    INVALID_IMAGE = "invalid_image"
    UNSUPPORTED_LAYOUT = "unsupported_layout"
    UNSUPPORTED = "unsupported"
    CONFLICT = "conflict"
    EMPTY = "empty"
    OCCUPIED = "occupied"


class ConfidenceSemantics(str, Enum):
    """Declares what a score means instead of implying calibration."""

    CALIBRATED_CORRECTNESS = "calibrated_correctness_probability"
    CLASSIFIER_PROBABILITY = "raw_classifier_probability"
    EMBEDDING_SIMILARITY = "embedding_similarity"
    TEMPLATE_SIMILARITY = "template_similarity"
    OCR_SEQUENCE = "ocr_sequence_confidence"
    GEOMETRY = "geometry_confidence"
    CROP_QUALITY = "crop_quality_score"
    LEGACY_UNCALIBRATED = "legacy_uncalibrated_score"


JsonScalar = str | int | float | bool
UnitInterval = Annotated[float, Field(ge=0.0, le=1.0)]
SourceBox = tuple[int, int, int, int]


class StrictModel(BaseModel):
    """Shared immutable, typo-rejecting schema behavior."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Resolution(StrictModel):
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class CandidateEvidence(StrictModel):
    candidate_id: str | None = None
    label: str | None = None
    raw: str | None = None
    scores: dict[str, float] = Field(default_factory=dict)


class ExtractedField(StrictModel):
    raw: str | None = None
    value: JsonScalar | None = None
    status: ExtractionStatus
    confidence: UnitInterval | None = None
    confidence_semantics: ConfidenceSemantics | None = None
    source_box: SourceBox | None = None
    candidates: tuple[CandidateEvidence, ...] = ()
    validation_messages: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_semantics(self) -> Self:
        if self.confidence is not None and self.confidence_semantics is None:
            raise ValueError("confidence_semantics is required when confidence is present")
        if self.status is ExtractionStatus.OK and self.value is None:
            raise ValueError("status=ok requires a value; zero is a valid value")
        return self


class HeroResult(StrictModel):
    hero_id: str | None = None
    name: str | None = None
    status: ExtractionStatus
    confidence: UnitInterval | None = None
    confidence_semantics: ConfidenceSemantics | None = None
    source_box: SourceBox | None = None
    candidates: tuple[CandidateEvidence, ...] = ()

    @model_validator(mode="after")
    def validate_accepted_hero(self) -> Self:
        if self.status is ExtractionStatus.OK and self.hero_id is None:
            raise ValueError("an accepted hero requires hero_id")
        if self.confidence is not None and self.confidence_semantics is None:
            raise ValueError("confidence_semantics is required when confidence is present")
        return self


class ItemResult(StrictModel):
    slot: int = Field(ge=0, le=6)
    item_id: str | None = None
    name: str | None = None
    status: ExtractionStatus
    confidence: UnitInterval | None = None
    confidence_semantics: ConfidenceSemantics | None = None
    source_box: SourceBox | None = None
    candidates: tuple[CandidateEvidence, ...] = ()

    @model_validator(mode="after")
    def validate_item_state(self) -> Self:
        if self.status is ExtractionStatus.OK and self.item_id is None:
            raise ValueError("an accepted item requires item_id")
        if self.status is ExtractionStatus.EMPTY and self.item_id is not None:
            raise ValueError("an empty slot cannot contain item_id")
        if self.confidence is not None and self.confidence_semantics is None:
            raise ValueError("confidence_semantics is required when confidence is present")
        return self


class PlayerResult(StrictModel):
    row: int = Field(ge=0, le=4)
    hero: HeroResult | None = None
    items: tuple[ItemResult, ...] = ()
    fields: dict[str, ExtractedField] = Field(default_factory=dict)


class TeamResult(StrictModel):
    side: str
    players: tuple[PlayerResult, ...] = ()


class QualityEvidence(StrictModel):
    status: ExtractionStatus
    blur_score: UnitInterval | None = None
    compression_score: UnitInterval | None = None


class GeometryEvidence(StrictModel):
    profile: str | None = None
    confidence: UnitInterval | None = None
    confidence_semantics: ConfidenceSemantics | None = None
    fallback_used: bool = False
    hypotheses_attempted: int = Field(default=0, ge=0)
    failure_reason: str | None = None

    @model_validator(mode="after")
    def validate_geometry_confidence(self) -> Self:
        if self.confidence is not None and self.confidence_semantics is None:
            raise ValueError("confidence_semantics is required when confidence is present")
        return self


class SourceEvidence(StrictModel):
    original_resolution: Resolution
    viewport: SourceBox | None = None
    quality: QualityEvidence
    geometry: GeometryEvidence


class Provenance(StrictModel):
    engine_version: str
    catalog_version: str | None = None
    ui_profile: str | None = None
    model_versions: dict[str, str] = Field(default_factory=dict)
    preprocessing_version: str
    processing_time_ms: float = Field(ge=0.0)


class ExtractionResult(StrictModel):
    schema_version: str = "2.0"
    status: ExtractionStatus
    screen_type: str | None = None
    provenance: Provenance
    source: SourceEvidence
    metadata: dict[str, ExtractedField] = Field(default_factory=dict)
    teams: tuple[TeamResult, ...] = ()
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def reject_removed_played_at_field(self) -> Self:
        if "played_at" in self.metadata:
            raise ValueError("played_at has been removed from the extraction schema")
        return self
