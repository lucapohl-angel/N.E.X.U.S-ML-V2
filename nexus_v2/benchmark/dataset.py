"""Safe loading and checksum validation for private external benchmark data."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from nexus_v2.schemas.annotation import AnnotationManifest, BenchmarkSample

MANIFEST_NAME = "manifest.json"
MAX_MANIFEST_BYTES = 10 * 1024 * 1024
DEFAULT_MAX_IMAGE_BYTES = 50 * 1024 * 1024


class DatasetValidationError(ValueError):
    """Raised when a dataset cannot be safely or truthfully benchmarked."""


@dataclass(frozen=True)
class LoadedDataset:
    requested_path: Path
    root: Path
    manifest_path: Path | None
    manifest_sha256: str | None
    manifest: AnnotationManifest | None
    no_data_reason: str | None = None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_dataset(path: Path) -> LoadedDataset:
    requested = path.expanduser()
    manifest_was_requested = requested.suffix.lower() == ".json" and not requested.is_dir()
    manifest_path = requested if manifest_was_requested else requested / MANIFEST_NAME
    root = requested.parent.resolve() if manifest_was_requested else requested.resolve()

    if not manifest_path.exists():
        return LoadedDataset(
            requested_path=requested,
            root=root,
            manifest_path=None,
            manifest_sha256=None,
            manifest=None,
            no_data_reason=f"No {MANIFEST_NAME} exists at {manifest_path}",
        )
    if not manifest_path.is_file():
        raise DatasetValidationError(f"Dataset manifest is not a regular file: {manifest_path}")
    if manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
        raise DatasetValidationError("Dataset manifest exceeds the 10 MiB safety limit")

    raw = manifest_path.read_bytes()
    try:
        manifest = AnnotationManifest.model_validate_json(raw)
    except ValidationError as exc:
        raise DatasetValidationError(f"Invalid annotation manifest: {exc}") from exc

    return LoadedDataset(
        requested_path=requested,
        root=root,
        manifest_path=manifest_path.resolve(),
        manifest_sha256=hashlib.sha256(raw).hexdigest(),
        manifest=manifest,
        no_data_reason=("The manifest contains zero samples" if not manifest.samples else None),
    )


def resolve_sample_image(
    dataset: LoadedDataset,
    sample: BenchmarkSample,
    *,
    max_image_bytes: int = DEFAULT_MAX_IMAGE_BYTES,
) -> Path:
    candidate = Path(sample.image_path).expanduser()
    resolved = (
        candidate.resolve() if candidate.is_absolute() else (dataset.root / candidate).resolve()
    )

    if not resolved.is_file():
        raise DatasetValidationError(f"{sample.sample_id}: image is not a regular file: {resolved}")
    size = resolved.stat().st_size
    if size <= 0:
        raise DatasetValidationError(f"{sample.sample_id}: image file is empty")
    if size > max_image_bytes:
        raise DatasetValidationError(
            f"{sample.sample_id}: image is {size} bytes, over the {max_image_bytes}-byte limit"
        )
    actual_sha256 = sha256_file(resolved)
    if actual_sha256 != sample.sha256:
        raise DatasetValidationError(
            f"{sample.sample_id}: SHA-256 mismatch (expected {sample.sha256}, got {actual_sha256})"
        )
    return resolved
