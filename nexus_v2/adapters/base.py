"""Typed engine-neutral contract consumed by the benchmark runner."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from nexus_v2.schemas.annotation import BenchmarkSample, OccupancyStatus, TeamSide
from nexus_v2.schemas.result import ConfidenceSemantics, ExtractionStatus


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EngineCapabilities(StrictModel):
    hero_candidate_depth: int = Field(default=1, ge=0)
    item_candidate_depth: int = Field(default=1, ge=0)
    calibrated_confidence: bool = False


class RowPrediction(StrictModel):
    team: TeamSide
    row: int = Field(ge=0, le=4)
    y_start: int = Field(ge=0)
    y_end: int = Field(gt=0)


class HeroPrediction(StrictModel):
    team: TeamSide
    row: int = Field(ge=0, le=4)
    class_id: str | None = None
    status: ExtractionStatus
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence_semantics: ConfidenceSemantics | None = None
    candidates: tuple[str, ...] = ()


class ItemPrediction(StrictModel):
    team: TeamSide
    row: int = Field(ge=0, le=4)
    slot: int = Field(ge=0, le=5)
    occupancy: OccupancyStatus
    class_id: str | None = None
    status: ExtractionStatus
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence_semantics: ConfidenceSemantics | None = None
    candidates: tuple[str, ...] = ()


class FieldPrediction(StrictModel):
    field: str
    value: str | int | float | bool | None = None
    raw: str | None = None
    status: ExtractionStatus
    team: TeamSide | None = None
    row: int | None = Field(default=None, ge=0, le=4)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence_semantics: ConfidenceSemantics | None = None


class BenchmarkPrediction(StrictModel):
    rows: tuple[RowPrediction, ...] = ()
    heroes: tuple[HeroPrediction, ...] = ()
    items: tuple[ItemPrediction, ...] = ()
    fields: tuple[FieldPrediction, ...] = ()
    semantic_json: dict[str, Any]
    capabilities: EngineCapabilities


class EngineRun(StrictModel):
    engine_id: str
    engine_version: str
    prediction: BenchmarkPrediction
    raw_result: dict[str, Any]
    latency_ms: float = Field(ge=0.0)
    peak_memory_mib: float | None = Field(default=None, ge=0.0)
    diagnostics: tuple[str, ...] = ()


@runtime_checkable
class EngineAdapter(Protocol):
    """Protocol implemented by V1 and all future benchmarkable engines."""

    @property
    def engine_id(self) -> str:
        """Stable adapter identifier."""

        ...

    @property
    def engine_version(self) -> str:
        """Exact code/model version represented by this adapter."""

        ...

    def extract(self, *, sample: BenchmarkSample, image_path: Path) -> EngineRun:
        """Run one benchmark sample without mutating source data."""

        ...
