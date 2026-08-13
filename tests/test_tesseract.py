from __future__ import annotations

import os
from pathlib import Path

import pytest

from nexus_v2.tesseract import TesseractUnavailableError, resolve_tesseract_cmd


def _executable(path: Path) -> Path:
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | 0o111)
    return path


def test_explicit_tesseract_path_has_priority(tmp_path: Path) -> None:
    executable = _executable(tmp_path / "custom-tesseract")
    assert resolve_tesseract_cmd(executable, environ={}) == executable.resolve()


def test_environment_tesseract_path_is_portable(tmp_path: Path) -> None:
    executable = _executable(tmp_path / "environment-tesseract")
    assert resolve_tesseract_cmd(environ={"NEXUS_TESSERACT_CMD": str(executable)}) == (
        executable.resolve()
    )


def test_invalid_override_fails_clearly(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    with pytest.raises(TesseractUnavailableError, match="not usable"):
        resolve_tesseract_cmd(missing, environ=os.environ)
