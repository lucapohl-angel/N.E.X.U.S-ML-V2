from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from nexus_v2.adapters import LegacyV1Adapter
from nexus_v2.benchmark.models import ReportStatus
from nexus_v2.benchmark.runner import run_benchmark


def test_absent_private_dataset_produces_no_data_report(tmp_path: Path) -> None:
    report = run_benchmark(
        dataset_path=tmp_path / "not-mounted",
        adapter=LegacyV1Adapter(),
        max_image_bytes=1024,
    )
    assert report.status is ReportStatus.NO_DATA
    assert report.discovered_samples == 0
    assert report.metrics.hero_top1_accuracy.value is None
    assert (
        report.gate_reason
        == f"No manifest.json exists at {tmp_path / 'not-mounted' / 'manifest.json'}"
    )


def test_unapproved_sample_blocks_before_image_access(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    manifest = {
        "dataset_version": "test-only",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "samples": [
            {
                "sample_id": "shot-1",
                "match_group_id": "match-1",
                "image_path": "not-present.png",
                "sha256": "0" * 64,
                "approval": "unreviewed",
                "source": {"width": 1920, "height": 1080},
            }
        ],
    }
    (dataset / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    report = run_benchmark(
        dataset_path=dataset,
        adapter=LegacyV1Adapter(),
        max_image_bytes=1024,
    )
    assert report.status is ReportStatus.BLOCKED
    assert report.executed_samples == 0
    assert report.gate_reason is not None and "unapproved" in report.gate_reason
