from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from nexus_v2.benchmark.dataset import (
    DatasetValidationError,
    load_dataset,
    resolve_sample_image,
)


def _manifest(image_name: str, sha256: str) -> dict[str, object]:
    return {
        "dataset_version": "test-only",
        "annotation_version": "1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "samples": [
            {
                "sample_id": "shot-1",
                "match_group_id": "match-1",
                "image_path": image_name,
                "sha256": sha256,
                "approval": "approved",
                "reviewer": "test-reviewer",
                "reviewed_at": datetime.now(timezone.utc).isoformat(),
                "source": {"width": 1, "height": 1},
                "annotation": {"screen_type": "screen1"},
            }
        ],
    }


def test_missing_manifest_is_an_explicit_no_data_state(tmp_path: Path) -> None:
    loaded = load_dataset(tmp_path / "private-release")
    assert loaded.manifest is None
    assert loaded.no_data_reason is not None


def test_external_image_checksum_is_verified(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "private-release"
    dataset_dir.mkdir()
    image = dataset_dir / "shot.bin"
    image.write_bytes(b"private-test-image")
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    (dataset_dir / "manifest.json").write_text(
        json.dumps(_manifest(image.name, digest)), encoding="utf-8"
    )

    loaded = load_dataset(dataset_dir)
    assert loaded.manifest is not None
    assert resolve_sample_image(loaded, loaded.manifest.samples[0]) == image.resolve()


def test_checksum_mismatch_blocks_execution(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "private-release"
    dataset_dir.mkdir()
    image = dataset_dir / "shot.bin"
    image.write_bytes(b"private-test-image")
    (dataset_dir / "manifest.json").write_text(
        json.dumps(_manifest(image.name, "0" * 64)), encoding="utf-8"
    )

    loaded = load_dataset(dataset_dir)
    assert loaded.manifest is not None
    with pytest.raises(DatasetValidationError, match="SHA-256 mismatch"):
        resolve_sample_image(loaded, loaded.manifest.samples[0])
