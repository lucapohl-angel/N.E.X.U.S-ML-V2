"""Isolated subprocess entry point for one unmodified V1 extraction."""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
from pathlib import Path
from typing import Any

from nexus_v2.tesseract import configure_pytesseract


def _peak_memory_mib() -> float | None:
    try:
        import resource
    except ImportError:
        return None

    peak = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if sys.platform == "darwin":
        return peak / (1024.0 * 1024.0)
    return peak / 1024.0


def execute(image: Path, screen: str, tesseract_cmd: str | None) -> dict[str, Any]:
    """Import V1, repair only its process-local executable path, and run once."""

    from main import extract

    resolved_tesseract = configure_pytesseract(tesseract_cmd)
    started = time.perf_counter()
    with contextlib.redirect_stdout(sys.stderr):
        result = extract(str(image), screen)
    latency_ms = (time.perf_counter() - started) * 1000.0
    return {
        "result": result,
        "latency_ms": latency_ms,
        "peak_memory_mib": _peak_memory_mib(),
        "tesseract_cmd": str(resolved_tesseract),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--screen", choices=[f"screen{i}" for i in range(1, 6)], required=True)
    parser.add_argument("--tesseract-cmd")
    args = parser.parse_args(argv)

    try:
        payload = execute(args.image, args.screen, args.tesseract_cmd)
    except Exception as exc:
        print(f"V1 execution failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
