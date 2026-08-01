"""Canonical serialization and immutable on-disk snapshot handling."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import suppress
from pathlib import Path

from pydantic import ValidationError

from nexus_v2.catalog.models import CatalogSnapshot


class CatalogStorageError(RuntimeError):
    """Raised when immutable catalog storage cannot be read or written safely."""


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True, separators=(",", ": "))
        + "\n"
    ).encode("utf-8")


def snapshot_bytes(snapshot: CatalogSnapshot) -> bytes:
    return canonical_json_bytes(snapshot.model_dump(mode="json"))


def snapshot_sha256(snapshot: CatalogSnapshot) -> str:
    return hashlib.sha256(snapshot_bytes(snapshot)).hexdigest()


def resolve_manifest_path(path: Path) -> Path:
    return path / "catalog.json" if path.is_dir() else path


def load_snapshot(path: Path, *, verify_sidecar: bool = True) -> tuple[CatalogSnapshot, str, Path]:
    manifest_path = resolve_manifest_path(path)
    try:
        raw = manifest_path.read_bytes()
    except OSError as exc:
        raise CatalogStorageError(
            f"could not read catalog snapshot {manifest_path}: {exc}"
        ) from exc
    if len(raw) > 64 * 1024 * 1024:
        raise CatalogStorageError("catalog manifest exceeds the 64 MiB safety limit")
    try:
        snapshot = CatalogSnapshot.model_validate_json(raw)
    except ValidationError as exc:
        raise CatalogStorageError(f"catalog manifest is invalid: {exc}") from exc
    digest = hashlib.sha256(canonical_json_bytes(snapshot.model_dump(mode="json"))).hexdigest()
    if verify_sidecar:
        sidecar = manifest_path.with_name("catalog.sha256")
        try:
            expected = sidecar.read_text(encoding="ascii").strip().split()[0]
        except (OSError, IndexError) as exc:
            raise CatalogStorageError(f"could not read catalog digest sidecar: {exc}") from exc
        if expected != digest:
            raise CatalogStorageError(
                f"catalog digest mismatch: sidecar has {expected!r}, computed {digest!r}"
            )
    return snapshot, digest, manifest_path


def atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)
        raise CatalogStorageError(f"could not atomically write {path}: {exc}") from exc


def write_json(path: Path, value: object) -> None:
    atomic_write_bytes(path, canonical_json_bytes(value))


def write_immutable_snapshot(root: Path, snapshot: CatalogSnapshot) -> str:
    if (root / "catalog.json").exists() or (root / "catalog.sha256").exists():
        raise CatalogStorageError(f"snapshot manifest already exists: {root}")
    root.mkdir(parents=True, exist_ok=True)
    payload = snapshot_bytes(snapshot)
    digest = hashlib.sha256(payload).hexdigest()
    atomic_write_bytes(root / "catalog.json", payload)
    atomic_write_bytes(root / "catalog.sha256", f"{digest}  catalog.json\n".encode("ascii"))
    return digest
