"""Typed benchmark report models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from nexus_v2.adapters.base import EngineRun
from nexus_v2.schemas.annotation import BenchmarkSample


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MetricStatus(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class ReportStatus(str, Enum):
    COMPLETED = "completed"
    NO_DATA = "no_data"
    BLOCKED = "blocked"


class MetricResult(StrictModel):
    status: MetricStatus
    value: Any = None
    numerator: int | float | None = None
    denominator: int | float | None = None
    unit: str | None = None
    reason: str | None = None


class BenchmarkMetrics(StrictModel):
    geometry_success: MetricResult
    normalized_coordinate_error: MetricResult
    hero_top1_accuracy: MetricResult
    hero_top3_accuracy: MetricResult
    hero_per_class_recall: MetricResult
    item_top1_accuracy: MetricResult
    item_top3_accuracy: MetricResult
    item_occupancy_accuracy: MetricResult
    item_per_class_recall: MetricResult
    unknown_false_accept_rate: MetricResult
    unknown_false_reject_rate: MetricResult
    ocr_exact_sequence_accuracy: MetricResult
    ocr_character_error_rate: MetricResult
    numeric_exact_value_accuracy: MetricResult
    zero_missing_confusion: MetricResult
    confidence_calibration: MetricResult
    full_json_exact_match: MetricResult
    critical_field_exact_match: MetricResult
    latency: MetricResult
    memory: MetricResult
    selective_accuracy: MetricResult
    slices: MetricResult


class SampleExecution(StrictModel):
    sample: BenchmarkSample
    run: EngineRun | None = None
    error: str | None = None


class BenchmarkReport(StrictModel):
    report_version: str = "1.0"
    generated_at: datetime
    status: ReportStatus
    gate_reason: str | None = None
    dataset_path: str
    dataset_version: str | None = None
    dataset_manifest_sha256: str | None = None
    engine_id: str
    engine_version: str
    discovered_samples: int = Field(ge=0)
    approved_samples: int = Field(ge=0)
    executed_samples: int = Field(ge=0)
    successful_samples: int = Field(ge=0)
    failed_samples: dict[str, str] = Field(default_factory=dict)
    metrics: BenchmarkMetrics
