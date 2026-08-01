"""Human-reviewed promotion from immutable staging to immutable production."""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from nexus_v2.catalog.audit import audit_snapshot
from nexus_v2.catalog.models import CatalogAuditReport, CatalogSnapshot, SnapshotStatus
from nexus_v2.catalog.review import CatalogReviewStore, ReviewStoreError, apply_review_actions
from nexus_v2.catalog.storage import (
    CatalogStorageError,
    load_snapshot,
    write_immutable_snapshot,
    write_json,
)


class CatalogPromotionError(RuntimeError):
    def __init__(self, message: str, audit_report: CatalogAuditReport | None = None) -> None:
        super().__init__(message)
        self.audit_report = audit_report


@dataclass(frozen=True)
class PromotionResult:
    production_path: Path
    snapshot: CatalogSnapshot
    snapshot_sha256: str
    audit_report: CatalogAuditReport


def promote_catalog(
    *,
    staging_path: Path,
    production_root: Path,
    actions_path: Path | None = None,
) -> PromotionResult:
    try:
        staging, staging_digest, manifest = load_snapshot(staging_path)
    except CatalogStorageError as exc:
        raise CatalogPromotionError(str(exc)) from exc
    store = CatalogReviewStore(actions_path or manifest.parent / "review_actions.jsonl")
    try:
        actions = store.load(snapshot_sha256=staging_digest)
    except ReviewStoreError as exc:
        raise CatalogPromotionError(str(exc)) from exc
    reviewed = apply_review_actions(staging, actions).model_copy(
        update={"status": SnapshotStatus.PRODUCTION}
    )
    destination = production_root / reviewed.catalog_version
    if destination.exists():
        raise CatalogPromotionError(f"production snapshot already exists: {destination}")
    production_root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{reviewed.catalog_version}.", dir=production_root))
    try:
        source_assets = manifest.parent / "assets"
        if source_assets.is_dir():
            shutil.copytree(source_assets, temporary / "assets")
        digest = write_immutable_snapshot(temporary, reviewed)
        audit = audit_snapshot(reviewed, temporary)
        if not audit.promotion_ready:
            raise CatalogPromotionError(
                "promotion blocked by mandatory audit or review issues",
                audit_report=audit,
            )
        write_json(temporary / "audit_report.json", audit.model_dump(mode="json"))
        os.replace(temporary, destination)
        return PromotionResult(
            production_path=destination,
            snapshot=reviewed,
            snapshot_sha256=digest,
            audit_report=audit,
        )
    except CatalogPromotionError:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    except (OSError, CatalogStorageError, ValueError) as exc:
        shutil.rmtree(temporary, ignore_errors=True)
        raise CatalogPromotionError(str(exc)) from exc
