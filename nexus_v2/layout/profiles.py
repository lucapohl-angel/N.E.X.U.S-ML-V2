"""Versioned reference-profile schema and validated local registry."""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing_extensions import Self


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ScreenType(str, Enum):
    HERO_ITEM_BUILD = "hero_item_build"
    OVERALL = "overall"
    DPS = "dps"
    FARM = "farm"
    TEAM = "team"


class ProfileVerification(str, Enum):
    VERIFIED = "verified"
    BOOTSTRAP_UNVERIFIED = "bootstrap_unverified"


class AnchorFamily(str, Enum):
    CONTROL = "control"
    HEADER = "header"
    PANEL = "panel"
    FOOTER = "footer"


class FieldKind(str, Enum):
    HERO = "hero"
    ITEM = "item"
    OCR = "ocr"
    METADATA = "metadata"


class FieldScope(str, Enum):
    VIEWPORT = "viewport"
    PANEL = "panel"
    ROW = "row"


class TeamSide(str, Enum):
    ALLY = "ally"
    ENEMY = "enemy"


BoxF = tuple[float, float, float, float]
OCR_PARSERS = frozenset(
    {
        "battle_id",
        "battle_id_18",
        "datetime",
        "decimal",
        "duration",
        "large_integer",
        "level",
        "percentage",
        "player_name",
        "result",
        "short_integer",
        "small_integer",
    }
)
PointF = tuple[float, float]


def _validate_box(value: BoxF, *, label: str) -> BoxF:
    x1, y1, x2, y2 = value
    if x2 <= x1 or y2 <= y1:
        raise ValueError(f"{label} must have increasing edges")
    return value


def _safe_asset_path(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not value:
        raise ValueError("profile asset paths must be non-empty safe relative paths")
    return path.as_posix()


class CanonicalSize(StrictModel):
    width: int = Field(gt=0)
    height: int = Field(gt=0)

    @property
    def aspect_ratio(self) -> float:
        return self.width / self.height


class CompatibilityMetadata(StrictModel):
    ui_family: str = Field(min_length=1)
    patch_min: str | None = None
    patch_max: str | None = None
    languages: tuple[str, ...] = ()
    allowed_aspect_error: float = Field(default=0.035, gt=0.0, le=0.25)
    allows_cropped_edges: bool = True
    requires_second_device_verification: bool = False
    notes: tuple[str, ...] = ()


class DynamicMask(StrictModel):
    mask_id: str = Field(min_length=1)
    region: BoxF
    reason: str = Field(min_length=1)

    @field_validator("region")
    @classmethod
    def validate_region(cls, value: BoxF) -> BoxF:
        return _validate_box(value, label="dynamic mask")


class AnchorDefinition(StrictModel):
    anchor_id: str = Field(min_length=1)
    stable_version: str = Field(min_length=1)
    family: AnchorFamily
    canonical_box: BoxF
    search_box: BoxF
    template_path: str
    mask_path: str | None = None
    screen_types: tuple[ScreenType, ...] = ()
    minimum_score: float = Field(ge=0.0, le=1.0)
    minimum_margin: float = Field(ge=0.0, le=1.0)

    @field_validator("canonical_box", "search_box")
    @classmethod
    def validate_boxes(cls, value: BoxF) -> BoxF:
        return _validate_box(value, label="anchor box")

    @field_validator("template_path", "mask_path")
    @classmethod
    def validate_paths(cls, value: str | None) -> str | None:
        return None if value is None else _safe_asset_path(value)

    @property
    def canonical_center(self) -> PointF:
        x1, y1, x2, y2 = self.canonical_box
        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


class ScreenEvidenceDefinition(StrictModel):
    evidence_id: str = Field(min_length=1)
    screen_type: ScreenType
    kind: str = Field(pattern=r"^(tab|header|panel)$")
    canonical_box: BoxF
    template_path: str
    mask_path: str | None = None
    weight: float = Field(gt=0.0, le=1.0)

    @field_validator("canonical_box")
    @classmethod
    def validate_box(cls, value: BoxF) -> BoxF:
        return _validate_box(value, label="screen evidence box")

    @field_validator("template_path", "mask_path")
    @classmethod
    def validate_paths(cls, value: str | None) -> str | None:
        return None if value is None else _safe_asset_path(value)


class PanelDefinition(StrictModel):
    side: TeamSide
    canonical_box: BoxF
    edge_search_radius: float = Field(default=18.0, gt=0.0, le=80.0)
    independent_registration: bool = True

    @field_validator("canonical_box")
    @classmethod
    def validate_box(cls, value: BoxF) -> BoxF:
        return _validate_box(value, label="panel box")


class RowRelation(StrictModel):
    count: int = Field(default=5, ge=1, le=20)
    first_top: float = Field(ge=0.0)
    height: float = Field(gt=0.0)
    step: float = Field(gt=0.0)
    search_radius: float = Field(default=16.0, gt=0.0, le=80.0)
    spacing_tolerance: float = Field(default=0.12, gt=0.0, le=0.5)


class SlotRelation(StrictModel):
    count: int = Field(default=6, ge=1, le=12)
    centers: dict[TeamSide, tuple[float, ...]]
    center_y_in_row: float = Field(gt=0.0)
    diameter: float = Field(gt=0.0)
    search_radius: float = Field(default=8.0, gt=0.0, le=30.0)

    @model_validator(mode="after")
    def validate_centers(self) -> Self:
        for side in TeamSide:
            values = self.centers.get(side)
            if values is None or len(values) != self.count:
                raise ValueError(f"slot relation requires {self.count} centers for {side.value}")
            if any(right <= left for left, right in zip(values, values[1:], strict=False)):
                raise ValueError("slot centers must increase monotonically")
        return self


class SemanticFieldDefinition(StrictModel):
    field_id: str = Field(min_length=1)
    kind: FieldKind
    scope: FieldScope
    screen_types: tuple[ScreenType, ...]
    canonical_box: BoxF
    side: TeamSide | None = None
    row_repeat: bool = False
    row_step: float = Field(default=0.0, ge=0.0)
    slot_repeat: bool = False
    slot_step: float = Field(default=0.0, ge=0.0)
    parser: str | None = None
    tight_padding: float = Field(default=0.0, ge=0.0, le=20.0)
    context_padding: float = Field(default=4.0, ge=0.0, le=40.0)
    mask_shape: str = Field(default="rectangle", pattern=r"^(rectangle|ellipse)$")
    dynamic: bool = True

    @field_validator("canonical_box")
    @classmethod
    def validate_box(cls, value: BoxF) -> BoxF:
        return _validate_box(value, label="semantic field box")

    @model_validator(mode="after")
    def validate_repetition(self) -> Self:
        if self.scope is not FieldScope.VIEWPORT and self.side is None:
            raise ValueError("panel and row fields require an explicit independently solved side")
        if self.row_repeat and self.row_step <= 0.0:
            raise ValueError("row_repeat requires a positive row_step")
        if self.slot_repeat and self.slot_step <= 0.0:
            raise ValueError("slot_repeat requires a positive slot_step")
        if not self.screen_types:
            raise ValueError("semantic fields require compatible screen types")
        if self.kind in {FieldKind.OCR, FieldKind.METADATA}:
            if self.parser not in OCR_PARSERS:
                raise ValueError("OCR and metadata fields require a supported semantic parser")
        elif self.parser is not None:
            raise ValueError("visual fields cannot declare an OCR parser")
        return self


class ReferenceProfile(StrictModel):
    schema_version: str = "2.0"
    profile_id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    profile_version: str = Field(min_length=1)
    verification: ProfileVerification
    verification_evidence: tuple[str, ...] = ()
    runtime_enabled: bool
    canonical_size: CanonicalSize
    screen_types: tuple[ScreenType, ...]
    compatibility: CompatibilityMetadata
    panels: tuple[PanelDefinition, ...]
    row_relation: RowRelation
    slot_relation: SlotRelation
    anchors: tuple[AnchorDefinition, ...]
    screen_evidence: tuple[ScreenEvidenceDefinition, ...]
    dynamic_masks: tuple[DynamicMask, ...]
    fields: tuple[SemanticFieldDefinition, ...]

    @model_validator(mode="after")
    def validate_contract(self) -> Self:
        if set(self.screen_types) != set(ScreenType):
            raise ValueError("a complete post-match profile must declare all five screen types")
        if {panel.side for panel in self.panels} != set(TeamSide):
            raise ValueError("profile must define independent ally and enemy panels")
        if any(not panel.independent_registration for panel in self.panels):
            raise ValueError("panel mirroring is not a valid V2 profile contract")
        if self.runtime_enabled and self.verification is not ProfileVerification.VERIFIED:
            raise ValueError("only verified profiles may be enabled for runtime acceptance")
        if not self.anchors and self.runtime_enabled:
            raise ValueError("runtime profiles require stable anchors")
        return self

    def resolve_asset(self, profile_path: Path, relative_path: str) -> Path:
        resolved = (profile_path.parent / relative_path).resolve()
        root = profile_path.parent.resolve()
        if not resolved.is_relative_to(root):
            raise ValueError("profile asset resolves outside its profile directory")
        return resolved


class LoadedProfile(StrictModel):
    profile: ReferenceProfile
    path: Path


class ProfileRegistry:
    """Load profiles deterministically and reject broken fixture references."""

    def __init__(self, loaded: tuple[LoadedProfile, ...]) -> None:
        ids = [item.profile.profile_id for item in loaded]
        if len(ids) != len(set(ids)):
            raise ValueError("profile IDs must be unique")
        self._loaded = tuple(sorted(loaded, key=lambda item: item.profile.profile_id))

    @classmethod
    def load(cls, root: Path) -> ProfileRegistry:
        loaded: list[LoadedProfile] = []
        for path in sorted(root.glob("*/profile.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            profile = ReferenceProfile.model_validate(payload)
            for relative in [
                *(anchor.template_path for anchor in profile.anchors),
                *(anchor.mask_path for anchor in profile.anchors if anchor.mask_path),
                *(evidence.template_path for evidence in profile.screen_evidence),
                *(evidence.mask_path for evidence in profile.screen_evidence if evidence.mask_path),
            ]:
                asset = profile.resolve_asset(path, relative)
                if not asset.is_file():
                    raise ValueError(f"profile asset is missing: {asset}")
            loaded.append(LoadedProfile(profile=profile, path=path))
        if not loaded:
            raise ValueError(f"no reference profiles found under {root}")
        return cls(tuple(loaded))

    @property
    def profiles(self) -> tuple[LoadedProfile, ...]:
        return self._loaded

    @property
    def runtime_profiles(self) -> tuple[LoadedProfile, ...]:
        return tuple(item for item in self._loaded if item.profile.runtime_enabled)

    def get(self, profile_id: str) -> LoadedProfile:
        for loaded in self._loaded:
            if loaded.profile.profile_id == profile_id:
                return loaded
        raise KeyError(profile_id)
