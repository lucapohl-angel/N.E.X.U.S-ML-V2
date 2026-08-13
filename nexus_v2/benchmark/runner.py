"""Dataset-gated orchestration for a real engine benchmark."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from nexus_v2.adapters.base import EngineAdapter
from nexus_v2.benchmark.dataset import DatasetValidationError, load_dataset, resolve_sample_image
from nexus_v2.benchmark.metrics import calculate_metrics, empty_metrics
from nexus_v2.benchmark.models import BenchmarkReport, ReportStatus, SampleExecution
from nexus_v2.schemas.annotation import ApprovalStatus


def _now() -> datetime:
    return datetime.now(timezone.utc)


def run_benchmark(
    *,
    dataset_path: Path,
    adapter: EngineAdapter,
    max_image_bytes: int,
) -> BenchmarkReport:
    """Validate the full dataset first, then invoke the adapter for every sample."""

    try:
        dataset = load_dataset(dataset_path)
    except DatasetValidationError as exc:
        reason = str(exc)
        return BenchmarkReport(
            generated_at=_now(),
            status=ReportStatus.BLOCKED,
            gate_reason=reason,
            dataset_path=str(dataset_path),
            engine_id=adapter.engine_id,
            engine_version=adapter.engine_version,
            discovered_samples=0,
            approved_samples=0,
            executed_samples=0,
            successful_samples=0,
            metrics=empty_metrics(reason),
        )

    if dataset.manifest is None or not dataset.manifest.samples:
        reason = dataset.no_data_reason or "No benchmark samples were discovered"
        return BenchmarkReport(
            generated_at=_now(),
            status=ReportStatus.NO_DATA,
            gate_reason=reason,
            dataset_path=str(dataset_path),
            dataset_manifest_sha256=dataset.manifest_sha256,
            engine_id=adapter.engine_id,
            engine_version=adapter.engine_version,
            discovered_samples=0,
            approved_samples=0,
            executed_samples=0,
            successful_samples=0,
            metrics=empty_metrics(reason),
        )

    manifest = dataset.manifest
    approved = [sample for sample in manifest.samples if sample.approval is ApprovalStatus.APPROVED]
    unapproved = [
        sample.sample_id
        for sample in manifest.samples
        if sample.approval is not ApprovalStatus.APPROVED
    ]
    if unapproved:
        reason = "Every sample must be approved before benchmarking; unapproved: " + ", ".join(
            sorted(unapproved)
        )
        return BenchmarkReport(
            generated_at=_now(),
            status=ReportStatus.BLOCKED,
            gate_reason=reason,
            dataset_path=str(dataset_path),
            dataset_version=manifest.dataset_version,
            dataset_manifest_sha256=dataset.manifest_sha256,
            engine_id=adapter.engine_id,
            engine_version=adapter.engine_version,
            discovered_samples=len(manifest.samples),
            approved_samples=len(approved),
            executed_samples=0,
            successful_samples=0,
            metrics=empty_metrics(reason),
        )

    resolved_images: dict[str, Path] = {}
    validation_errors: dict[str, str] = {}
    for sample in manifest.samples:
        try:
            resolved_images[sample.sample_id] = resolve_sample_image(
                dataset, sample, max_image_bytes=max_image_bytes
            )
        except DatasetValidationError as exc:
            validation_errors[sample.sample_id] = str(exc)
    if validation_errors:
        reason = "Dataset integrity validation failed; no samples were executed"
        return BenchmarkReport(
            generated_at=_now(),
            status=ReportStatus.BLOCKED,
            gate_reason=reason,
            dataset_path=str(dataset_path),
            dataset_version=manifest.dataset_version,
            dataset_manifest_sha256=dataset.manifest_sha256,
            engine_id=adapter.engine_id,
            engine_version=adapter.engine_version,
            discovered_samples=len(manifest.samples),
            approved_samples=len(approved),
            executed_samples=0,
            successful_samples=0,
            failed_samples=validation_errors,
            metrics=empty_metrics(reason),
        )

    executions: list[SampleExecution] = []
    failures: dict[str, str] = {}
    for sample in manifest.samples:
        try:
            engine_run = adapter.extract(
                sample=sample, image_path=resolved_images[sample.sample_id]
            )
            executions.append(SampleExecution(sample=sample, run=engine_run))
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            failures[sample.sample_id] = error
            executions.append(SampleExecution(sample=sample, error=error))

    successful_count = sum(execution.run is not None for execution in executions)
    status = ReportStatus.COMPLETED if not failures else ReportStatus.BLOCKED
    gate_reason = None if not failures else "One or more engine executions failed"
    return BenchmarkReport(
        generated_at=_now(),
        status=status,
        gate_reason=gate_reason,
        dataset_path=str(dataset_path),
        dataset_version=manifest.dataset_version,
        dataset_manifest_sha256=dataset.manifest_sha256,
        engine_id=adapter.engine_id,
        engine_version=adapter.engine_version,
        discovered_samples=len(manifest.samples),
        approved_samples=len(approved),
        executed_samples=len(executions),
        successful_samples=successful_count,
        failed_samples=failures,
        metrics=calculate_metrics(executions),
    )
