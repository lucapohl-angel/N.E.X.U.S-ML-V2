from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus_v2.cli import main


def test_benchmark_report_option_writes_truthful_no_data_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset = tmp_path / "missing-dataset"
    report_path = tmp_path / "evaluation" / "reports" / "v1.json"

    exit_code = main(
        [
            "benchmark",
            "--engine",
            "v1",
            "--dataset",
            str(dataset),
            "--report",
            str(report_path),
        ]
    )

    assert exit_code == 2
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "no_data"
    assert report["discovered_samples"] == 0
    assert report["executed_samples"] == 0
    assert report["metrics"]["hero_top1_accuracy"]["status"] == "unavailable"
    assert json.loads(capsys.readouterr().out) == report
