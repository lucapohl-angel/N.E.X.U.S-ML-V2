from __future__ import annotations

from datetime import datetime, timezone

from nexus_v2.adapters.base import (
    BenchmarkPrediction,
    EngineCapabilities,
    EngineRun,
    FieldPrediction,
    HeroPrediction,
    ItemPrediction,
    RowPrediction,
)
from nexus_v2.benchmark.metrics import calculate_metrics
from nexus_v2.benchmark.models import MetricStatus, SampleExecution
from nexus_v2.schemas.annotation import (
    ApprovalStatus,
    BenchmarkAnnotation,
    BenchmarkSample,
    FieldGroundTruth,
    GeometryGroundTruth,
    HeroGroundTruth,
    ItemGroundTruth,
    OccupancyStatus,
    RowGroundTruth,
    ScreenType,
    SourceMetadata,
    TeamSide,
)
from nexus_v2.schemas.result import ConfidenceSemantics, ExtractionStatus


def _execution() -> SampleExecution:
    annotation = BenchmarkAnnotation(
        screen_type=ScreenType.SCREEN1,
        geometry=GeometryGroundTruth(
            rows=(RowGroundTruth(team=TeamSide.ALLY, row=0, y_start=10, y_end=30),)
        ),
        heroes=(
            HeroGroundTruth(
                team=TeamSide.ALLY, row=0, legacy_id=17, native_width=40, native_height=40
            ),
        ),
        items=(
            ItemGroundTruth(
                team=TeamSide.ALLY,
                row=0,
                slot=0,
                occupancy=OccupancyStatus.OCCUPIED,
                legacy_name="Blade of Despair",
                critical=True,
                native_width=36,
                native_height=36,
            ),
            ItemGroundTruth(
                team=TeamSide.ALLY,
                row=0,
                slot=1,
                occupancy=OccupancyStatus.EMPTY,
            ),
        ),
        fields=(
            FieldGroundTruth(field="battle_id", value="001", raw="001", critical=True),
            FieldGroundTruth(field="kills", value=0, team=TeamSide.ALLY, row=0),
        ),
        semantic_json={"semantic": "expected"},
    )
    sample = BenchmarkSample(
        sample_id="shot-1",
        match_group_id="match-1",
        image_path="shot.png",
        sha256="0" * 64,
        approval=ApprovalStatus.APPROVED,
        reviewer="reviewer",
        reviewed_at=datetime.now(timezone.utc),
        source=SourceMetadata(
            width=100,
            height=100,
            device_source="test-device",
            ui_profile="test-profile",
            patch="test-patch",
            compression="none",
            blur_bucket="sharp",
        ),
        annotation=annotation,
    )
    run = EngineRun(
        engine_id="legacy-v1",
        engine_version="test",
        prediction=BenchmarkPrediction(
            rows=(RowPrediction(team=TeamSide.ALLY, row=0, y_start=10, y_end=30),),
            heroes=(
                HeroPrediction(
                    team=TeamSide.ALLY,
                    row=0,
                    class_id="v1-hero-017",
                    status=ExtractionStatus.OK,
                    confidence=0.8,
                    confidence_semantics=ConfidenceSemantics.LEGACY_UNCALIBRATED,
                    candidates=("v1-hero-017", "v1-hero-001", "v1-hero-002"),
                ),
            ),
            items=(
                ItemPrediction(
                    team=TeamSide.ALLY,
                    row=0,
                    slot=0,
                    occupancy=OccupancyStatus.OCCUPIED,
                    class_id="v1-item:Blade of Despair",
                    status=ExtractionStatus.OK,
                    confidence=0.7,
                    confidence_semantics=ConfidenceSemantics.LEGACY_UNCALIBRATED,
                    candidates=(
                        "v1-item:Blade of Despair",
                        "v1-item:Dagger",
                        "v1-item:Knife",
                    ),
                ),
                ItemPrediction(
                    team=TeamSide.ALLY,
                    row=0,
                    slot=1,
                    occupancy=OccupancyStatus.EMPTY,
                    status=ExtractionStatus.EMPTY,
                ),
            ),
            fields=(
                FieldPrediction(
                    field="battle_id",
                    value="001",
                    raw="001",
                    status=ExtractionStatus.OK,
                    confidence=0.0,
                    confidence_semantics=ConfidenceSemantics.LEGACY_UNCALIBRATED,
                ),
                FieldPrediction(
                    field="kills",
                    value=0,
                    raw="0",
                    status=ExtractionStatus.OK,
                    team=TeamSide.ALLY,
                    row=0,
                    confidence=0.0,
                    confidence_semantics=ConfidenceSemantics.LEGACY_UNCALIBRATED,
                ),
            ),
            semantic_json={"semantic": "expected"},
            capabilities=EngineCapabilities(hero_candidate_depth=3, item_candidate_depth=3),
        ),
        raw_result={},
        latency_ms=100.0,
        peak_memory_mib=50.0,
    )
    return SampleExecution(sample=sample, run=run)


def test_required_metrics_are_computed_with_denominators() -> None:
    metrics = calculate_metrics([_execution()])

    assert metrics.geometry_success.value == 1.0
    assert metrics.normalized_coordinate_error.value == 0.0
    assert metrics.hero_top1_accuracy.value == 1.0
    assert metrics.hero_top3_accuracy.value == 1.0
    assert metrics.item_top1_accuracy.value == 1.0
    assert metrics.item_occupancy_accuracy.value == 1.0
    assert metrics.ocr_exact_sequence_accuracy.value == 1.0
    assert metrics.ocr_character_error_rate.value == 0.0
    assert metrics.numeric_exact_value_accuracy.value == 1.0
    assert metrics.full_json_exact_match.value == 1.0
    assert metrics.critical_field_exact_match.value == 1.0
    assert metrics.confidence_calibration.status is MetricStatus.AVAILABLE
    assert metrics.latency.value["mean_ms"] == 100.0
    assert metrics.memory.value["max_peak_mib"] == 50.0
