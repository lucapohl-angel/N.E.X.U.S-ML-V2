"""Portable Tesseract discovery shared by the V2 compatibility layer."""

from __future__ import annotations

import os
import shutil
from collections.abc import Mapping
from pathlib import Path


class TesseractUnavailableError(RuntimeError):
    """Raised when no executable Tesseract installation can be resolved."""


def resolve_tesseract_cmd(
    explicit: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Resolve Tesseract by explicit path, environment override, then ``PATH``.

    ``NEXUS_TESSERACT_CMD`` is the sole environment override. The returned path
    is absolute and executable; no platform-specific install location is baked
    into V2.
    """

    environment = os.environ if environ is None else environ
    requested = str(explicit) if explicit is not None else environment.get("NEXUS_TESSERACT_CMD")

    if requested:
        located = shutil.which(requested)
        candidate = Path(located) if located else Path(requested).expanduser()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.resolve()
        raise TesseractUnavailableError(f"Tesseract executable is not usable: {candidate}")

    located = shutil.which("tesseract")
    if located:
        return Path(located).resolve()

    raise TesseractUnavailableError(
        "Tesseract was not found. Install it or set NEXUS_TESSERACT_CMD to an executable path."
    )


def configure_pytesseract(explicit: str | Path | None = None) -> Path:
    """Resolve Tesseract and configure pytesseract for the current process."""

    import pytesseract  # type: ignore[import-untyped]

    executable = resolve_tesseract_cmd(explicit)
    pytesseract.pytesseract.tesseract_cmd = str(executable)
    return executable
