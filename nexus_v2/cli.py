"""Command-line entry points for the Phase 0 benchmark vertical slice."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from nexus_v2.adapters import LegacyV1Adapter
from nexus_v2.benchmark.dataset import DEFAULT_MAX_IMAGE_BYTES
from nexus_v2.benchmark.models import ReportStatus
from nexus_v2.benchmark.runner import run_benchmark
from nexus_v2.tesseract import TesseractUnavailableError, resolve_tesseract_cmd


def _write_report(payload: str, output: Path | None) -> None:
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload + "\n", encoding="utf-8")
    print(payload)


def _benchmark(args: argparse.Namespace) -> int:
    dataset_arg = args.dataset or os.environ.get("NEXUS_BENCHMARK_DATASET")
    dataset = Path(dataset_arg) if dataset_arg else Path("data/benchmarks/release-v1")
    adapter = LegacyV1Adapter(
        tesseract_cmd=args.tesseract_cmd,
        timeout_seconds=args.timeout_seconds,
    )
    report = run_benchmark(
        dataset_path=dataset,
        adapter=adapter,
        max_image_bytes=args.max_image_mib * 1024 * 1024,
    )
    _write_report(report.model_dump_json(indent=2), args.report)
    return 0 if report.status is ReportStatus.COMPLETED else 2


def _doctor(args: argparse.Namespace) -> int:
    checks: dict[str, Any] = {
        "python": sys.version.split()[0],
        "repository": str(Path.cwd()),
        "max_default_image_bytes": DEFAULT_MAX_IMAGE_BYTES,
    }
    healthy = True
    try:
        executable = resolve_tesseract_cmd(args.tesseract_cmd)
        completed = subprocess.run(
            [str(executable), "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        version_line = (completed.stdout or completed.stderr).splitlines()
        checks["tesseract"] = {
            "status": "ok" if completed.returncode == 0 else "error",
            "path": str(executable),
            "version": version_line[0] if version_line else None,
        }
        healthy = completed.returncode == 0
    except (TesseractUnavailableError, OSError, subprocess.SubprocessError) as exc:
        checks["tesseract"] = {"status": "error", "reason": str(exc)}
        healthy = False

    if args.json:
        print(json.dumps(checks, indent=2, sort_keys=True))
    else:
        for name, value in checks.items():
            print(f"{name}: {value}")
    return 0 if healthy else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nexus", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    benchmark = subparsers.add_parser(
        "benchmark", description="Run V1 on every approved, checksum-verified sample"
    )
    benchmark.add_argument(
        "--dataset",
        help=(
            "Dataset directory or manifest path; defaults to NEXUS_BENCHMARK_DATASET, "
            "then data/benchmarks/release-v1"
        ),
    )
    benchmark.add_argument("--engine", choices=["v1"], default="v1")
    benchmark.add_argument(
        "--report",
        "--output",
        dest="report",
        type=Path,
        help="Write the JSON report to this path; --output is a compatibility alias",
    )
    benchmark.add_argument("--tesseract-cmd")
    benchmark.add_argument("--timeout-seconds", type=float, default=120.0)
    benchmark.add_argument("--max-image-mib", type=int, default=50)
    benchmark.set_defaults(handler=_benchmark)

    doctor = subparsers.add_parser("doctor", description="Verify local runtime prerequisites")
    doctor.add_argument("--tesseract-cmd")
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(handler=_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "benchmark" and args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    if args.command == "benchmark" and args.max_image_mib <= 0:
        parser.error("--max-image-mib must be positive")
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
