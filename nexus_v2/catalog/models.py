"""Strict, immutable models for the V2 catalog lifecycle."""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing_extensions import Self


class CatalogModel(BaseModel):
    """Base model that rejects undocumented fields and in-memory mutation."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class CatalogKind(str, Enum):
    HERO = "hero"
    ITEM = "item"


class ReviewStatus(str, Enum):
    UNREVIEWED = "unreviewed"
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_PENDING = "changes_pending"


class ProvenanceStatus(str, Enum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    REJECTED = "rejected"


class SnapshotStatus(str, Enum):
    STAGING = "staging"
    PRODUCTION = "production"


class IssueSeverity(str, Enum):
    MANDATORY = "mandatory"
    WARNING = "warning"
    INFO = "info"


class MigrationStatus(str, Enum):
    MAPPED_UNREVIEWED = "mapped_unreviewed"
    AMBIGUOUS = "ambiguous"
    FAILED = "failed"


class AssetProvenance(CatalogModel):
    """Where bytes came from, without storing credentials or request headers."""

    source_adapter: str = Field(min_length=1)
    source_identity: str = Field(min_length=1)
    source_reference: str = Field(min_length=1)
    retrieved_at: datetime
    retrieval_method: str = Field(min_length=1)
    status: ProvenanceStatus = ProvenanceStatus.UNVERIFIED
    credential_environment_variables: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @field_validator("credential_environment_variables")
    @classmethod
    def validate_environment_names(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for name in value:
            if re.fullmatch(r"[A-Z][A-Z0-9_]*", name) is None:
                raise ValueError("credential environment variable names must be uppercase names")
        return value


class VisualVersion(CatalogModel):
    id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    asset_path: str = Field(min_length=1)
    sha256: str
    phash: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    mime_type: str = Field(pattern=r"^image/[a-z0-9.+-]+$")
    active_from_patch: str | None = None
    active_until_patch: str | None = None
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    provenance: AssetProvenance

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        normalized = value.lower()
        if re.fullmatch(r"[0-9a-f]{64}", normalized) is None:
            raise ValueError("sha256 must be 64 lowercase hexadecimal characters")
        return normalized

    @field_validator("phash")
    @classmethod
    def validate_phash(cls, value: str) -> str:
        normalized = value.lower()
        if re.fullmatch(r"[0-9a-f]{16}", normalized) is None:
            raise ValueError("phash must be 16 lowercase hexadecimal characters")
        return normalized

    @field_validator("asset_path")
    @classmethod
    def validate_asset_path(cls, value: str) -> str:
        if value.startswith(("/", "\\")) or "\\" in value:
            raise ValueError("asset_path must be a relative POSIX path")
        parts = value.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise ValueError("asset_path contains an unsafe path component")
        return value


class HeroRecord(CatalogModel):
    id: str = Field(pattern=r"^hero_[a-z0-9][a-z0-9_-]*$")
    canonical_name: str = Field(min_length=1)
    aliases: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    active_from_patch: str | None = None
    active_until_patch: str | None = None
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    visual_versions: tuple[VisualVersion, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_visual_ids(self) -> Self:
        ids = [visual.id for visual in self.visual_versions]
        if len(ids) != len(set(ids)):
            raise ValueError("visual version IDs must be unique within a hero")
        return self


class ItemRecord(CatalogModel):
    id: str = Field(pattern=r"^item_[a-z0-9][a-z0-9_-]*$")
    canonical_name: str = Field(min_length=1)
    aliases: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    active_from_patch: str | None = None
    active_until_patch: str | None = None
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    classification_enabled: bool = True
    visual_versions: tuple[VisualVersion, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_visual_ids(self) -> Self:
        ids = [visual.id for visual in self.visual_versions]
        if len(ids) != len(set(ids)):
            raise ValueError("visual version IDs must be unique within an item")
        return self


class ClassMapEntry(CatalogModel):
    index: int = Field(ge=0)
    stable_id: str = Field(min_length=1)


class CatalogSnapshot(CatalogModel):
    schema_version: str = "2.0"
    catalog_version: str = Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    generated_at: datetime
    status: SnapshotStatus = SnapshotStatus.STAGING
    previous_snapshot_sha256: str | None = None
    heroes: tuple[HeroRecord, ...] = ()
    items: tuple[ItemRecord, ...] = ()
    hero_class_map: tuple[ClassMapEntry, ...] = ()
    item_class_map: tuple[ClassMapEntry, ...] = ()

    @field_validator("previous_snapshot_sha256")
    @classmethod
    def validate_previous_hash(cls, value: str | None) -> str | None:
        if value is not None and re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValueError("previous_snapshot_sha256 must be a SHA-256 digest")
        return value

    @model_validator(mode="after")
    def validate_identity_and_class_maps(self) -> Self:
        records: tuple[HeroRecord | ItemRecord, ...] = (*self.heroes, *self.items)
        record_ids = [record.id for record in records]
        if len(record_ids) != len(set(record_ids)):
            raise ValueError("catalog record IDs must be globally unique")
        visual_ids = [visual.id for record in records for visual in record.visual_versions]
        if len(visual_ids) != len(set(visual_ids)):
            raise ValueError("visual version IDs must be globally unique")
        self._validate_class_map(
            self.hero_class_map,
            {record.id for record in self.heroes},
            "hero",
        )
        self._validate_class_map(
            self.item_class_map,
            {record.id for record in self.items if record.classification_enabled},
            "item",
        )
        return self

    @staticmethod
    def _validate_class_map(
        entries: tuple[ClassMapEntry, ...], expected_ids: set[str], kind: str
    ) -> None:
        indices = [entry.index for entry in entries]
        ids = [entry.stable_id for entry in entries]
        if indices != list(range(len(entries))):
            raise ValueError(f"{kind} class-map indices must be contiguous and ordered")
        if len(ids) != len(set(ids)):
            raise ValueError(f"{kind} class-map IDs must be unique")
        if set(ids) != expected_ids:
            raise ValueError(
                f"{kind} class map must contain every classifiable {kind} exactly once"
            )


class CatalogDiff(CatalogModel):
    old_catalog_version: str
    new_catalog_version: str
    added_class_ids: tuple[str, ...] = ()
    removed_class_ids: tuple[str, ...] = ()
    renamed_classes: dict[str, tuple[str, str]] = Field(default_factory=dict)
    changed_visual_classes: tuple[str, ...] = ()
    unchanged_class_ids: tuple[str, ...] = ()
    class_map_changes: dict[str, tuple[int | None, int | None]] = Field(default_factory=dict)


class CatalogAuditIssue(CatalogModel):
    severity: IssueSeverity
    code: str = Field(min_length=1, pattern=r"^[a-z0-9_]+$")
    message: str = Field(min_length=1)
    class_id: str | None = None
    visual_version_id: str | None = None
    asset_path: str | None = None
    related_ids: tuple[str, ...] = ()


class CatalogAuditReport(CatalogModel):
    report_version: str = "1.0"
    catalog_version: str
    snapshot_sha256: str
    audited_at: datetime
    hero_count: int = Field(ge=0)
    item_count: int = Field(ge=0)
    visual_version_count: int = Field(ge=0)
    decoded_asset_count: int = Field(ge=0)
    mandatory_issue_count: int = Field(ge=0)
    warning_issue_count: int = Field(ge=0)
    promotion_ready: bool
    issues: tuple[CatalogAuditIssue, ...] = ()


class ModelCatalogCompatibility(CatalogModel):
    model_id: str = Field(min_length=1)
    model_catalog_version: str = Field(min_length=1)
    runtime_catalog_version: str = Field(min_length=1)
    preprocessing_version: str = Field(min_length=1)
    input_size: tuple[int, int]
    supported_class_ids: tuple[str, ...]
    observed_visual_version_ids: tuple[str, ...]
    runtime_only_class_ids: tuple[str, ...]
    model_only_class_ids: tuple[str, ...]
    missing_observed_visual_version_ids: tuple[str, ...]
    classifier_compatible: bool
    prototype_fallback_required: bool


class MigrationMapping(CatalogModel):
    legacy_path: str
    kind: CatalogKind
    source_identity: str
    stable_id: str | None = None
    status: MigrationStatus
    match_basis: str | None = None
    ambiguity_candidates: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


class CatalogMigrationReport(CatalogModel):
    report_version: str = "1.0"
    catalog_version: str
    generated_at: datetime
    hero_files_discovered: int = Field(ge=0)
    item_files_discovered: int = Field(ge=0)
    mapped_files: int = Field(ge=0)
    ambiguous_files: int = Field(ge=0)
    failed_files: int = Field(ge=0)
    mappings: tuple[MigrationMapping, ...]


class SourceFailure(CatalogModel):
    source_adapter: str
    source_identity: str | None = None
    stage: str
    reason: str


class CatalogSyncReport(CatalogModel):
    report_version: str = "1.0"
    catalog_version: str
    generated_at: datetime
    snapshot_path: str
    snapshot_sha256: str
    hero_candidates: int = Field(ge=0)
    item_candidates: int = Field(ge=0)
    added_classes: tuple[str, ...] = ()
    changed_visual_classes: tuple[str, ...] = ()
    failed_downloads: tuple[SourceFailure, ...] = ()
    exact_duplicate_groups: tuple[tuple[str, ...], ...] = ()
    near_duplicate_groups: tuple[tuple[str, ...], ...] = ()


class ReviewAction(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"


class CatalogReviewRecord(CatalogModel):
    action_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    snapshot_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    catalog_version: str
    class_id: str
    visual_version_id: str | None = None
    action: ReviewAction
    reviewer: str = Field(min_length=1, max_length=200)
    reviewed_at: datetime
    comment: str = Field(default="", max_length=2000)
