from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from nexus_v2.adapters import EngineAdapter, LegacyV1Adapter


def test_legacy_adapter_satisfies_engine_protocol() -> None:
    assert isinstance(LegacyV1Adapter(), EngineAdapter)


@pytest.mark.integration
def test_isolated_legacy_runner_reports_missing_input() -> None:
    repository = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "nexus_v2.legacy_runner",
            "--image",
            str(repository / "does-not-exist.png"),
            "--screen",
            "screen1",
        ],
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 1
    assert "V1 execution failed" in completed.stderr
