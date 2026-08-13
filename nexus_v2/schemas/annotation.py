"""Engine-independent, review-gated benchmark annotation schemas."""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing_extensions import Self

from nexus_v2.schemas.result import ExtractionStatus, JsonScalar


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ApprovalStatus(str, Enum):
    UNREVIEWED = "unreviewed"
    APPROVED = "approved"
    REJECTED = "rejected"


class ScreenType(str, Enum):
    SCREEN1 = "screen1"
    SCREEN2 = "screen2"
    SCREEN3 = "screen3"
    SCREEN4 = "screen4"
    SCREEN5 = "screen5"


class TeamSide(str, Enum):
    ALLY = "ally"
    ENEMY = "enemy"


class OccupancyStatus(str, Enum):
    EMPTY = "empty"
    OCCUPIED = "occupied"
    INVALID_CROP = "invalid_crop"
    UNKNOWN = "unknown"


class SourceMetadata(StrictModel):
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    device_source: str | None = None
    ui_profile: str | None = None
    patch: str | None = None
    compression: str | None = None
    blur_bucket: str | None = None
    capture_session: str | None = None


class RowGroundTruth(StrictModel):
    team: TeamSide
    row: int = Field(ge=0, le=4)
    y_start: int = Field(ge=0)
    y_end: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_bounds(self) -> Self:
        if self.y_end <= self.y_start:
            raise ValueError("y_end must be greater than y_start")
        return self


class GeometryGroundTruth(StrictModel):
    viewport: tuple[int, int, int, int] | None = None
    rows: tuple[RowGroundTruth, ...] = ()


class HeroGroundTruth(StrictModel):
    team: TeamSide
    row: int = Field(ge=0, le=4)
    stable_id: str | None = None
    legacy_id: int | None = Field(default=None, gt=0)
    unknown: bool = False
    critical: bool = True
    native_width: int | None = Field(default=None, gt=0)
    native_height: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if not self.unknown and self.stable_id is None and self.legacy_id is None:
            raise ValueError("known hero ground truth requires stable_id or legacy_id")
        return self


class ItemGroundTruth(StrictModel):
    team: TeamSide
    row: int = Field(ge=0, le=4)
    slot: int = Field(ge=0, le=5)
    occupancy: OccupancyStatus
    stable_id: str | None = None
    legacy_name: str | None = None
    unknown_identity: bool = False
    critical: bool = False
    native_width: int | None = Field(default=None, gt=0)
    native_height: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        known_occupied = self.occupancy is OccupancyStatus.OCCUPIED and not self.unknown_identity
        if known_occupied and self.stable_id is None and self.legacy_name is None:
            raise ValueError("known occupied item requires stable_id or legacy_name")
        if self.occupancy is not OccupancyStatus.OCCUPIED and (
            self.stable_id is not None or self.legacy_name is not None
        ):
            raise ValueError("only occupied slots may carry item identity")
        return self


class FieldGroundTruth(StrictModel):
    field: str = Field(min_length=1)
    value: JsonScalar | None = None
    status: ExtractionStatus = ExtractionStatus.OK
    team: TeamSide | None = None
    row: int | None = Field(default=None, ge=0, le=4)
    raw: str | None = None
    critical: bool = False

    @model_validator(mode="after")
    def validate_location_and_value(self) -> Self:
        if (self.team is None) != (self.row is None):
            raise ValueError("team and row must either both be set or both be omitted")
        if self.status is ExtractionStatus.OK and self.value is None:
            raise ValueError("status=ok requires a value; use 0 for a true zero")
        return self


class BenchmarkAnnotation(StrictModel):
    annotation_version: str = "1.0"
    screen_type: ScreenType
    geometry: GeometryGroundTruth | None = None
    heroes: tuple[HeroGroundTruth, ...] = ()
    items: tuple[ItemGroundTruth, ...] = ()
    fields: tuple[FieldGroundTruth, ...] = ()
    semantic_json: dict[str, Any] | None = None


class BenchmarkSample(StrictModel):
    sample_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    match_group_id: str = Field(min_length=1)
    image_path: str = Field(min_length=1)
    sha256: str
    approval: ApprovalStatus = ApprovalStatus.UNREVIEWED
    reviewer: str | None = None
    reviewed_at: datetime | None = None
    source: SourceMetadata
    annotation: BenchmarkAnnotation | None = None
    slices: dict[str, str] = Field(default_factory=dict)

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        normalized = value.lower()
        if re.fullmatch(r"[0-9a-f]{64}", normalized) is None:
            raise ValueError("sha256 must contain exactly 64 hexadecimal characters")
        return normalized

    @model_validator(mode="after")
    def validate_review_gate(self) -> Self:
        if self.approval is ApprovalStatus.APPROVED:
            missing = [
                name
                for name, value in (
                    ("reviewer", self.reviewer),
                    ("reviewed_at", self.reviewed_at),
                    ("annotation", self.annotation),
                )
                if value is None
            ]
            if missing:
                raise ValueError(f"approved sample is missing: {', '.join(missing)}")
        return self


class AnnotationManifest(StrictModel):
    dataset_version: str = Field(min_length=1)
    annotation_version: str = "1.0"
    created_at: datetime
    samples: tuple[BenchmarkSample, ...] = ()

    @model_validator(mode="after")
    def validate_unique_samples(self) -> Self:
        sample_ids = [sample.sample_id for sample in self.samples]
        if len(sample_ids) != len(set(sample_ids)):
            raise ValueError("sample_id values must be unique")
        return self
