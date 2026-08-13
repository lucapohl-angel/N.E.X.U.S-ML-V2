"""Run the single-process N.E.X.U.S asynchronous extraction API."""

from __future__ import annotations

import argparse
from dataclasses import replace

import uvicorn

from nexus_v2.api.app import APISettings, create_app
from nexus_v2.runtime import PerformanceProfile


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nexus-api",
        description=(
            "Run one preloaded N.E.X.U.S engine with one serialized extraction worker. "
            "Do not add Uvicorn workers; each process would load a separate model set."
        ),
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--performance-profile",
        choices=tuple(profile.value for profile in PerformanceProfile),
        default=None,
        help="Override NEXUS_PERFORMANCE_PROFILE (default: auto).",
    )
    parser.add_argument(
        "--log-level",
        choices=("critical", "error", "warning", "info"),
        default="info",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 0 <= args.port <= 65535:
        raise SystemExit("--port must be between 0 and 65535")
    settings = APISettings.from_env()
    if args.performance_profile is not None:
        settings = replace(settings, performance_profile=str(args.performance_profile))
    application = create_app(settings=settings)
    uvicorn.run(
        application,
        host=str(args.host),
        port=int(args.port),
        workers=1,
        log_level=str(args.log_level),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
