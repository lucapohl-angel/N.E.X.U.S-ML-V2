"""Exact, denominator-carrying metrics for Phase 0 and later engine adapters."""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from collections.abc import Iterable
from statistics import mean
from typing import Any

from nexus_v2.adapters.base import FieldPrediction
from nexus_v2.benchmark.models import (
    BenchmarkMetrics,
    MetricResult,
    MetricStatus,
    SampleExecution,
)
from nexus_v2.schemas.annotation import (
    FieldGroundTruth,
    HeroGroundTruth,
    ItemGroundTruth,
    OccupancyStatus,
)
from nexus_v2.schemas.result import ExtractionStatus


def unavailable(reason: str) -> MetricResult:
    return MetricResult(status=MetricStatus.UNAVAILABLE, reason=reason)


def ratio(numerator: int | float, denominator: int | float, *, unit: str) -> MetricResult:
    if denominator == 0:
        return unavailable("No approved ground-truth observations for this metric")
    return MetricResult(
        status=MetricStatus.AVAILABLE,
        value=numerator / denominator,
        numerator=numerator,
        denominator=denominator,
        unit=unit,
    )


def _legacy_hero_truth(truth: HeroGroundTruth, engine_id: str) -> str | None:
    if engine_id == "legacy-v1" and truth.legacy_id is not None:
        return f"v1-hero-{truth.legacy_id:03d}"
    return truth.stable_id


def _legacy_item_truth(truth: ItemGroundTruth, engine_id: str) -> str | None:
    if engine_id == "legacy-v1" and truth.legacy_name is not None:
        return f"v1-item:{truth.legacy_name}"
    return truth.stable_id


def _levenshtein(left: str, right: str) -> int:
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for left_index, left_character in enumerate(left, 1):
        current = [left_index]
        for right_index, right_character in enumerate(right, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_character != right_character),
                )
            )
        previous = current
    return previous[-1]


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _field_key(field: FieldGroundTruth | FieldPrediction) -> tuple[object, object, str]:
    return (field.team, field.row, field.field)


def _exact_value(expected: object, predicted: object) -> bool:
    if isinstance(expected, bool) or isinstance(predicted, bool):
        return type(expected) is type(predicted) and expected == predicted
    if isinstance(expected, int | float) and isinstance(predicted, int | float):
        return float(expected) == float(predicted)
    return type(expected) is type(predicted) and expected == predicted


def _per_class_metric(correct: Counter[str], support: Counter[str]) -> MetricResult:
    if not support:
        return unavailable("No known-class annotations are available")
    value = {
        class_id: {
            "correct": correct[class_id],
            "support": count,
            "recall": correct[class_id] / count,
        }
        for class_id, count in sorted(support.items())
    }
    return MetricResult(
        status=MetricStatus.AVAILABLE,
        value=value,
        numerator=sum(correct.values()),
        denominator=sum(support.values()),
        unit="recall_by_class",
    )


def _calibration(events: list[tuple[float, bool, str]]) -> MetricResult:
    if not events:
        return unavailable("The engine emitted no scored predictions with approved truth")
    bins: list[dict[str, float | int]] = []
    expected_calibration_error = 0.0
    for lower_index in range(10):
        lower = lower_index / 10
        upper = (lower_index + 1) / 10
        bucket = [
            event
            for event in events
            if lower <= event[0] <= upper and (upper == 1 or event[0] < upper)
        ]
        if not bucket:
            continue
        average_confidence = mean(event[0] for event in bucket)
        accuracy = mean(float(event[1]) for event in bucket)
        expected_calibration_error += abs(accuracy - average_confidence) * len(bucket) / len(events)
        bins.append(
            {
                "lower": lower,
                "upper": upper,
                "count": len(bucket),
                "accuracy": accuracy,
                "average_confidence": average_confidence,
            }
        )
    brier = mean((confidence - float(correct)) ** 2 for confidence, correct, _ in events)
    semantics = sorted({semantics for _, _, semantics in events})
    return MetricResult(
        status=MetricStatus.AVAILABLE,
        value={
            "ece_10_bin": expected_calibration_error,
            "brier_score": brier,
            "bins": bins,
            "confidence_semantics_observed": semantics,
            "calibrated_probability_claim": semantics == ["calibrated_correctness_probability"],
        },
        denominator=len(events),
        unit="calibration",
    )


def _selective_accuracy(events: list[tuple[float, bool, str]]) -> MetricResult:
    if not events:
        return unavailable("The engine emitted no scored predictions with approved truth")
    points: list[dict[str, float | int]] = []
    for threshold in (0.0, 0.5, 0.7, 0.8, 0.9, 0.95, 0.99):
        accepted = [event for event in events if event[0] >= threshold]
        points.append(
            {
                "threshold": threshold,
                "accepted": len(accepted),
                "total": len(events),
                "coverage": len(accepted) / len(events),
                "accuracy": (mean(float(event[1]) for event in accepted) if accepted else 0.0),
            }
        )
    return MetricResult(
        status=MetricStatus.AVAILABLE,
        value=points,
        denominator=len(events),
        unit="accuracy_at_coverage",
    )


def empty_metrics(reason: str) -> BenchmarkMetrics:
    def missing() -> MetricResult:
        return unavailable(reason)

    return BenchmarkMetrics(
        geometry_success=missing(),
        normalized_coordinate_error=missing(),
        hero_top1_accuracy=missing(),
        hero_top3_accuracy=missing(),
        hero_per_class_recall=missing(),
        item_top1_accuracy=missing(),
        item_top3_accuracy=missing(),
        item_occupancy_accuracy=missing(),
        item_per_class_recall=missing(),
        unknown_false_accept_rate=missing(),
        unknown_false_reject_rate=missing(),
        ocr_exact_sequence_accuracy=missing(),
        ocr_character_error_rate=missing(),
        numeric_exact_value_accuracy=missing(),
        zero_missing_confusion=missing(),
        confidence_calibration=missing(),
        full_json_exact_match=missing(),
        critical_field_exact_match=missing(),
        latency=missing(),
        memory=missing(),
        selective_accuracy=missing(),
        slices=missing(),
    )


def calculate_metrics(executions: Iterable[SampleExecution]) -> BenchmarkMetrics:
    successful = [execution for execution in executions if execution.run is not None]
    if not successful:
        return empty_metrics("No sample completed successfully")

    geometry_correct = 0
    geometry_total = 0
    normalized_errors: list[float] = []
    hero_correct = 0
    hero_total = 0
    hero_top3_correct = 0
    hero_top3_total = 0
    hero_top3_supported = True
    hero_support: Counter[str] = Counter()
    hero_class_correct: Counter[str] = Counter()
    item_correct = 0
    item_total = 0
    item_top3_correct = 0
    item_top3_total = 0
    item_top3_supported = True
    item_support: Counter[str] = Counter()
    item_class_correct: Counter[str] = Counter()
    occupancy_correct = 0
    occupancy_total = 0
    unknown_false_accept = 0
    unknown_truth_total = 0
    unknown_false_reject = 0
    known_truth_total = 0
    ocr_exact = 0
    ocr_total = 0
    character_edits = 0
    character_total = 0
    numeric_exact = 0
    numeric_total = 0
    zero_expected_missing = 0
    missing_expected_zero = 0
    full_json_correct = 0
    full_json_total = 0
    critical_correct = 0
    critical_total = 0
    calibration_events: list[tuple[float, bool, str]] = []
    native_dimension_stats: dict[str, list[bool]] = defaultdict(list)
    sample_outcomes: list[tuple[SampleExecution, bool | None, bool | None]] = []

    for execution in successful:
        run = execution.run
        annotation = execution.sample.annotation
        if run is None or annotation is None:
            continue
        prediction = run.prediction
        row_predictions = {(row.team, row.row): row for row in prediction.rows}
        hero_predictions = {(hero.team, hero.row): hero for hero in prediction.heroes}
        item_predictions = {(item.team, item.row, item.slot): item for item in prediction.items}
        field_predictions = {_field_key(field): field for field in prediction.fields}
        sample_critical_checks: list[bool] = []

        if annotation.geometry is not None and annotation.geometry.rows:
            geometry_total += 1
            geometry_checks: list[bool] = []
            for row_truth in annotation.geometry.rows:
                row_prediction = row_predictions.get((row_truth.team, row_truth.row))
                geometry_checks.append(row_prediction is not None)
                if row_prediction is not None:
                    height = execution.sample.source.height
                    normalized_errors.extend(
                        [
                            abs(row_prediction.y_start - row_truth.y_start) / height,
                            abs(row_prediction.y_end - row_truth.y_end) / height,
                        ]
                    )
            if all(geometry_checks) and len(row_predictions) == len(annotation.geometry.rows):
                geometry_correct += 1

        for hero_truth in annotation.heroes:
            hero_prediction = hero_predictions.get((hero_truth.team, hero_truth.row))
            expected_id = _legacy_hero_truth(hero_truth, run.engine_id)
            is_unknown = hero_truth.unknown
            predicted_known = (
                hero_prediction is not None
                and hero_prediction.status is ExtractionStatus.OK
                and hero_prediction.class_id is not None
            )
            if is_unknown:
                unknown_truth_total += 1
                if predicted_known:
                    unknown_false_accept += 1
                correct = not predicted_known
            else:
                known_truth_total += 1
                hero_total += 1
                if expected_id is not None:
                    hero_support[expected_id] += 1
                correct = (
                    predicted_known
                    and hero_prediction is not None
                    and hero_prediction.class_id == expected_id
                )
                if correct:
                    hero_correct += 1
                    if expected_id is not None:
                        hero_class_correct[expected_id] += 1
                if not predicted_known:
                    unknown_false_reject += 1
                if prediction.capabilities.hero_candidate_depth >= 3:
                    hero_top3_total += 1
                    if (
                        hero_prediction is not None
                        and expected_id in hero_prediction.candidates[:3]
                    ):
                        hero_top3_correct += 1
                else:
                    hero_top3_supported = False
            if hero_truth.critical:
                sample_critical_checks.append(correct)
            if hero_truth.native_width is not None and hero_truth.native_height is not None:
                native_dimension_stats[
                    f"hero:{hero_truth.native_width}x{hero_truth.native_height}"
                ].append(correct)
            if hero_prediction is not None and hero_prediction.confidence is not None:
                semantics = (
                    hero_prediction.confidence_semantics.value
                    if hero_prediction.confidence_semantics is not None
                    else "undeclared"
                )
                calibration_events.append((hero_prediction.confidence, correct, semantics))

        for item_truth in annotation.items:
            item_prediction = item_predictions.get(
                (item_truth.team, item_truth.row, item_truth.slot)
            )
            predicted_occupancy = (
                item_prediction.occupancy
                if item_prediction is not None
                else OccupancyStatus.UNKNOWN
            )
            occupancy_match = predicted_occupancy is item_truth.occupancy
            occupancy_total += 1
            occupancy_correct += int(occupancy_match)
            expected_id = _legacy_item_truth(item_truth, run.engine_id)
            if item_truth.occupancy is OccupancyStatus.OCCUPIED:
                predicted_known = (
                    item_prediction is not None
                    and item_prediction.status is ExtractionStatus.OK
                    and item_prediction.class_id is not None
                )
                if item_truth.unknown_identity:
                    unknown_truth_total += 1
                    if predicted_known:
                        unknown_false_accept += 1
                    correct = not predicted_known
                else:
                    known_truth_total += 1
                    item_total += 1
                    if expected_id is not None:
                        item_support[expected_id] += 1
                    correct = (
                        predicted_known
                        and item_prediction is not None
                        and item_prediction.class_id == expected_id
                    )
                    if correct:
                        item_correct += 1
                        if expected_id is not None:
                            item_class_correct[expected_id] += 1
                    if not predicted_known:
                        unknown_false_reject += 1
                    if prediction.capabilities.item_candidate_depth >= 3:
                        item_top3_total += 1
                        if (
                            item_prediction is not None
                            and expected_id in item_prediction.candidates[:3]
                        ):
                            item_top3_correct += 1
                    else:
                        item_top3_supported = False
            else:
                correct = occupancy_match
            if item_truth.critical:
                sample_critical_checks.append(correct)
            if item_truth.native_width is not None and item_truth.native_height is not None:
                native_dimension_stats[
                    f"item:{item_truth.native_width}x{item_truth.native_height}"
                ].append(correct)
            if item_prediction is not None and item_prediction.confidence is not None:
                semantics = (
                    item_prediction.confidence_semantics.value
                    if item_prediction.confidence_semantics is not None
                    else "undeclared"
                )
                calibration_events.append((item_prediction.confidence, correct, semantics))

        for field_truth in annotation.fields:
            field_prediction = field_predictions.get(_field_key(field_truth))
            if field_truth.status is ExtractionStatus.OK:
                ocr_total += 1
                predicted_text = (
                    ""
                    if field_prediction is None or field_prediction.value is None
                    else str(field_prediction.value)
                )
                expected_text = (
                    field_truth.raw if field_truth.raw is not None else str(field_truth.value)
                )
                exact = (
                    field_prediction is not None
                    and field_prediction.status is ExtractionStatus.OK
                    and predicted_text == expected_text
                )
                ocr_exact += int(exact)
                character_edits += _levenshtein(expected_text, predicted_text)
                character_total += len(expected_text)
                if isinstance(field_truth.value, int | float) and not isinstance(
                    field_truth.value, bool
                ):
                    numeric_total += 1
                    numeric_match = field_prediction is not None and _exact_value(
                        field_truth.value, field_prediction.value
                    )
                    numeric_exact += int(numeric_match)
                    if field_truth.value == 0 and (
                        field_prediction is None or field_prediction.value is None
                    ):
                        zero_expected_missing += 1
                if (
                    field_prediction is not None
                    and field_prediction.value == 0
                    and field_truth.value is None
                ):
                    missing_expected_zero += 1
            else:
                exact = (
                    field_prediction is None or field_prediction.status is not ExtractionStatus.OK
                )
                if field_prediction is not None and field_prediction.value == 0:
                    missing_expected_zero += 1
            if field_truth.critical:
                sample_critical_checks.append(exact)
            if field_prediction is not None and field_prediction.confidence is not None:
                semantics = (
                    field_prediction.confidence_semantics.value
                    if field_prediction.confidence_semantics is not None
                    else "undeclared"
                )
                calibration_events.append((field_prediction.confidence, exact, semantics))

        semantic_exact: bool | None = None
        if annotation.semantic_json is not None:
            full_json_total += 1
            expected_json = json.dumps(
                annotation.semantic_json, sort_keys=True, separators=(",", ":")
            )
            predicted_json = json.dumps(
                prediction.semantic_json, sort_keys=True, separators=(",", ":")
            )
            semantic_exact = expected_json == predicted_json
            full_json_correct += int(semantic_exact)

        critical_exact: bool | None = None
        if sample_critical_checks:
            critical_total += 1
            critical_exact = all(sample_critical_checks)
            critical_correct += int(critical_exact)
        sample_outcomes.append((execution, critical_exact, semantic_exact))

    latency_values = [execution.run.latency_ms for execution in successful if execution.run]
    memory_values = [
        execution.run.peak_memory_mib
        for execution in successful
        if execution.run is not None and execution.run.peak_memory_mib is not None
    ]
    latency_metric = MetricResult(
        status=MetricStatus.AVAILABLE,
        value={
            "mean_ms": mean(latency_values),
            "p50_ms": _percentile(latency_values, 0.50),
            "p95_ms": _percentile(latency_values, 0.95),
            "max_ms": max(latency_values),
        },
        denominator=len(latency_values),
        unit="milliseconds_per_screenshot",
    )
    memory_metric = (
        MetricResult(
            status=MetricStatus.AVAILABLE,
            value={
                "mean_peak_mib": mean(memory_values),
                "max_peak_mib": max(memory_values),
            },
            denominator=len(memory_values),
            unit="mebibytes_peak_rss",
        )
        if memory_values
        else unavailable("Peak RSS is unavailable on this platform")
    )

    slice_dimensions: dict[str, dict[str, list[bool]]] = defaultdict(lambda: defaultdict(list))
    for execution, critical_exact, semantic_exact in sample_outcomes:
        sample = execution.sample
        aspect_divisor = math.gcd(sample.source.width, sample.source.height)
        dimension_values = {
            "screen_type": sample.annotation.screen_type.value if sample.annotation else None,
            "device_source": sample.source.device_source,
            "resolution": f"{sample.source.width}x{sample.source.height}",
            "aspect_ratio": (
                f"{sample.source.width // aspect_divisor}:{sample.source.height // aspect_divisor}"
            ),
            "ui_profile": sample.source.ui_profile,
            "game_patch": sample.source.patch,
            "compression": sample.source.compression,
            "blur": sample.source.blur_bucket,
        }
        for custom_key, custom_value in sample.slices.items():
            dimension_values[f"custom:{custom_key}"] = custom_value
        outcome = critical_exact if critical_exact is not None else semantic_exact
        if outcome is None:
            continue
        for dimension, value in dimension_values.items():
            if value is not None:
                slice_dimensions[dimension][value].append(outcome)
    slice_value: dict[str, Any] = {}
    required_dimensions = (
        "screen_type",
        "device_source",
        "resolution",
        "aspect_ratio",
        "ui_profile",
        "game_patch",
        "compression",
        "blur",
    )
    for dimension in required_dimensions:
        groups = slice_dimensions.get(dimension, {})
        slice_value[dimension] = (
            {
                "status": "available",
                "groups": {
                    group: {
                        "correct": sum(outcomes),
                        "support": len(outcomes),
                        "accuracy": sum(outcomes) / len(outcomes),
                    }
                    for group, outcomes in sorted(groups.items())
                },
            }
            if groups
            else {"status": "unavailable", "reason": "Annotation metadata is absent"}
        )
    slice_value["class_frequency"] = {
        "status": "available" if hero_support or item_support else "unavailable",
        "hero_support": dict(sorted(hero_support.items())),
        "item_support": dict(sorted(item_support.items())),
    }
    slice_value["native_icon_dimensions"] = (
        {
            "status": "available",
            "groups": {
                group: {
                    "correct": sum(outcomes),
                    "support": len(outcomes),
                    "accuracy": sum(outcomes) / len(outcomes),
                }
                for group, outcomes in sorted(native_dimension_stats.items())
            },
        }
        if native_dimension_stats
        else {"status": "unavailable", "reason": "Native crop dimensions are absent"}
    )
    for dimension, groups in slice_dimensions.items():
        if not dimension.startswith("custom:"):
            continue
        slice_value[dimension] = {
            "status": "available",
            "groups": {
                group: {
                    "correct": sum(outcomes),
                    "support": len(outcomes),
                    "accuracy": sum(outcomes) / len(outcomes),
                }
                for group, outcomes in sorted(groups.items())
            },
        }

    top3_hero_metric = (
        ratio(hero_top3_correct, hero_top3_total, unit="fraction")
        if hero_top3_supported and hero_top3_total
        else unavailable("The adapter does not expose at least three hero candidates")
    )
    top3_item_metric = (
        ratio(item_top3_correct, item_top3_total, unit="fraction")
        if item_top3_supported and item_top3_total
        else unavailable("The adapter does not expose at least three item candidates")
    )
    normalized_error_metric = (
        MetricResult(
            status=MetricStatus.AVAILABLE,
            value=mean(normalized_errors),
            denominator=len(normalized_errors),
            unit="fraction_of_source_height",
        )
        if normalized_errors
        else unavailable("No matched annotated row edges are available")
    )

    return BenchmarkMetrics(
        geometry_success=ratio(geometry_correct, geometry_total, unit="fraction"),
        normalized_coordinate_error=normalized_error_metric,
        hero_top1_accuracy=ratio(hero_correct, hero_total, unit="fraction"),
        hero_top3_accuracy=top3_hero_metric,
        hero_per_class_recall=_per_class_metric(hero_class_correct, hero_support),
        item_top1_accuracy=ratio(item_correct, item_total, unit="fraction"),
        item_top3_accuracy=top3_item_metric,
        item_occupancy_accuracy=ratio(occupancy_correct, occupancy_total, unit="fraction"),
        item_per_class_recall=_per_class_metric(item_class_correct, item_support),
        unknown_false_accept_rate=ratio(unknown_false_accept, unknown_truth_total, unit="fraction"),
        unknown_false_reject_rate=ratio(unknown_false_reject, known_truth_total, unit="fraction"),
        ocr_exact_sequence_accuracy=ratio(ocr_exact, ocr_total, unit="fraction"),
        ocr_character_error_rate=ratio(
            character_edits, character_total, unit="edits_per_character"
        ),
        numeric_exact_value_accuracy=ratio(numeric_exact, numeric_total, unit="fraction"),
        zero_missing_confusion=MetricResult(
            status=MetricStatus.AVAILABLE,
            value={
                "true_zero_predicted_missing": zero_expected_missing,
                "missing_predicted_zero": missing_expected_zero,
            },
            denominator=ocr_total,
            unit="count",
        ),
        confidence_calibration=_calibration(calibration_events),
        full_json_exact_match=ratio(full_json_correct, full_json_total, unit="fraction"),
        critical_field_exact_match=ratio(critical_correct, critical_total, unit="fraction"),
        latency=latency_metric,
        memory=memory_metric,
        selective_accuracy=_selective_accuracy(calibration_events),
        slices=MetricResult(
            status=MetricStatus.AVAILABLE,
            value=slice_value,
            denominator=len(sample_outcomes),
            unit="accuracy_by_slice",
        ),
    )
