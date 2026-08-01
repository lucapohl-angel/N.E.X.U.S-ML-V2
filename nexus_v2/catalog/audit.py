"""Catalog integrity audit and model/runtime compatibility checks."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from nexus_v2.catalog.images import AssetValidationError, phash_distance, validate_local_image
from nexus_v2.catalog.models import (
    CatalogAuditIssue,
    CatalogAuditReport,
    CatalogSnapshot,
    HeroRecord,
    IssueSeverity,
    ItemRecord,
    ModelCatalogCompatibility,
    ProvenanceStatus,
    ReviewStatus,
)
from nexus_v2.catalog.sources import normalize_label
from nexus_v2.catalog.storage import snapshot_sha256

PLACEHOLDER_LABELS = frozenset(
    {"placeholder", "unknown", "test", "todo", "tbd", "sample", "dummy", "empty slot"}
)
SECRET_VALUE_PATTERNS = (
    re.compile(
        r"(?i)(authorization|cookie|api[_-]?key|access[_-]?token)\s*[:=]\s*['\"]?[A-Za-z0-9+/=_-]{12,}"
    ),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{12,}"),
)


def _issue(
    severity: IssueSeverity,
    code: str,
    message: str,
    *,
    class_id: str | None = None,
    visual_id: str | None = None,
    asset_path: str | None = None,
    related_ids: tuple[str, ...] = (),
) -> CatalogAuditIssue:
    return CatalogAuditIssue(
        severity=severity,
        code=code,
        message=message,
        class_id=class_id,
        visual_version_id=visual_id,
        asset_path=asset_path,
        related_ids=related_ids,
    )


def audit_snapshot(snapshot: CatalogSnapshot, snapshot_root: Path) -> CatalogAuditReport:
    """Re-decode every referenced asset and enforce the human promotion gate."""

    issues: list[CatalogAuditIssue] = []
    decoded_count = 0
    hashes: dict[str, list[tuple[str, str]]] = defaultdict(list)
    phashes: list[tuple[str, str, str, str]] = []
    normalized_names: dict[tuple[str, str], list[str]] = defaultdict(list)
    records: tuple[HeroRecord | ItemRecord, ...] = (*snapshot.heroes, *snapshot.items)
    root = snapshot_root.resolve()
    for record in records:
        kind = "hero" if record.id.startswith("hero_") else "item"
        normalized_names[(kind, normalize_label(record.canonical_name))].append(record.id)
        if normalize_label(record.canonical_name) in PLACEHOLDER_LABELS:
            issues.append(
                _issue(
                    IssueSeverity.MANDATORY,
                    "placeholder_record",
                    f"{record.canonical_name!r} is a forbidden production placeholder label",
                    class_id=record.id,
                )
            )
        if record.review_status is not ReviewStatus.APPROVED:
            issues.append(
                _issue(
                    IssueSeverity.MANDATORY,
                    "unreviewed_class",
                    f"class review status is {record.review_status.value}",
                    class_id=record.id,
                )
            )
        for visual in record.visual_versions:
            if visual.review_status is not ReviewStatus.APPROVED:
                issues.append(
                    _issue(
                        IssueSeverity.MANDATORY,
                        "unreviewed_visual",
                        f"visual review status is {visual.review_status.value}",
                        class_id=record.id,
                        visual_id=visual.id,
                        asset_path=visual.asset_path,
                    )
                )
            if visual.provenance.status is not ProvenanceStatus.VERIFIED:
                issues.append(
                    _issue(
                        IssueSeverity.MANDATORY,
                        "unverified_provenance",
                        f"asset provenance status is {visual.provenance.status.value}",
                        class_id=record.id,
                        visual_id=visual.id,
                        asset_path=visual.asset_path,
                    )
                )
            path = snapshot_root / visual.asset_path
            try:
                resolved = path.resolve()
                if not resolved.is_relative_to(root):
                    raise AssetValidationError("asset path escapes snapshot root")
                validated = validate_local_image(resolved)
                decoded_count += 1
            except AssetValidationError as exc:
                issues.append(
                    _issue(
                        IssueSeverity.MANDATORY,
                        "missing_or_invalid_asset",
                        str(exc),
                        class_id=record.id,
                        visual_id=visual.id,
                        asset_path=visual.asset_path,
                    )
                )
                continue
            if validated.sha256 != visual.sha256:
                issues.append(
                    _issue(
                        IssueSeverity.MANDATORY,
                        "sha256_mismatch",
                        "asset SHA-256 differs from the immutable manifest",
                        class_id=record.id,
                        visual_id=visual.id,
                        asset_path=visual.asset_path,
                    )
                )
            if validated.phash != visual.phash:
                issues.append(
                    _issue(
                        IssueSeverity.MANDATORY,
                        "phash_mismatch",
                        "asset perceptual hash differs from the immutable manifest",
                        class_id=record.id,
                        visual_id=visual.id,
                        asset_path=visual.asset_path,
                    )
                )
            if (validated.width, validated.height) != (visual.width, visual.height):
                issues.append(
                    _issue(
                        IssueSeverity.MANDATORY,
                        "dimension_mismatch",
                        "decoded dimensions differ from the immutable manifest",
                        class_id=record.id,
                        visual_id=visual.id,
                        asset_path=visual.asset_path,
                    )
                )
            if validated.mime_type != visual.mime_type:
                issues.append(
                    _issue(
                        IssueSeverity.MANDATORY,
                        "mime_mismatch",
                        "decoded MIME type differs from the immutable manifest",
                        class_id=record.id,
                        visual_id=visual.id,
                        asset_path=visual.asset_path,
                    )
                )
            ratio = validated.width / validated.height
            if ratio < 0.5 or ratio > 2.0:
                issues.append(
                    _issue(
                        IssueSeverity.WARNING,
                        "unexpected_aspect_ratio",
                        f"asset aspect ratio {ratio:.3f} is outside 0.5..2.0",
                        class_id=record.id,
                        visual_id=visual.id,
                        asset_path=visual.asset_path,
                    )
                )
            hashes[validated.sha256].append((record.id, visual.id))
            phashes.append((record.id, visual.id, validated.sha256, validated.phash))

    for (kind, normalized), ids in sorted(normalized_names.items()):
        if normalized and len(ids) > 1:
            issues.append(
                _issue(
                    IssueSeverity.MANDATORY,
                    "conflicting_normalized_label",
                    f"multiple {kind} records normalize to {normalized!r}",
                    related_ids=tuple(sorted(ids)),
                )
            )
    for duplicate_hash, values in sorted(hashes.items()):
        class_ids = {value[0] for value in values}
        if len(class_ids) > 1:
            related = tuple(sorted(value[1] for value in values))
            issues.append(
                _issue(
                    IssueSeverity.MANDATORY,
                    "exact_duplicate",
                    f"different classes share exact asset SHA-256 {duplicate_hash}",
                    related_ids=related,
                )
            )
    for index, (left_class, left_visual, left_sha, left_hash) in enumerate(phashes):
        for right_class, right_visual, right_sha, right_hash in phashes[index + 1 :]:
            if left_class == right_class or left_sha == right_sha:
                continue
            distance = phash_distance(left_hash, right_hash)
            if distance <= 4:
                issues.append(
                    _issue(
                        IssueSeverity.WARNING,
                        "near_duplicate",
                        f"visual pHash distance is {distance}; human comparison required",
                        related_ids=tuple(sorted((left_visual, right_visual))),
                    )
                )
    manifest_text = (
        (snapshot_root / "catalog.json").read_text(encoding="utf-8")
        if (snapshot_root / "catalog.json").is_file()
        else ""
    )
    for pattern in SECRET_VALUE_PATTERNS:
        if pattern.search(manifest_text):
            issues.append(
                _issue(
                    IssueSeverity.MANDATORY,
                    "secret_pattern",
                    "catalog manifest contains a credential-like value",
                )
            )
            break
    mandatory = sum(issue.severity is IssueSeverity.MANDATORY for issue in issues)
    warnings = sum(issue.severity is IssueSeverity.WARNING for issue in issues)
    return CatalogAuditReport(
        catalog_version=snapshot.catalog_version,
        snapshot_sha256=snapshot_sha256(snapshot),
        audited_at=datetime.now(timezone.utc),
        hero_count=len(snapshot.heroes),
        item_count=len(snapshot.items),
        visual_version_count=sum(len(record.visual_versions) for record in records),
        decoded_asset_count=decoded_count,
        mandatory_issue_count=mandatory,
        warning_issue_count=warnings,
        promotion_ready=mandatory == 0,
        issues=tuple(issues),
    )


def model_catalog_compatibility(
    *,
    snapshot: CatalogSnapshot,
    model_id: str,
    model_catalog_version: str,
    supported_class_ids: tuple[str, ...],
    observed_visual_version_ids: tuple[str, ...],
    preprocessing_version: str,
    input_size: tuple[int, int],
) -> ModelCatalogCompatibility:
    runtime_ids = {
        entry.stable_id for entry in (*snapshot.hero_class_map, *snapshot.item_class_map)
    }
    model_ids = set(supported_class_ids)
    records: tuple[HeroRecord | ItemRecord, ...] = (*snapshot.heroes, *snapshot.items)
    runtime_visual_ids = {visual.id for record in records for visual in record.visual_versions}
    runtime_only = tuple(sorted(runtime_ids - model_ids))
    model_only = tuple(sorted(model_ids - runtime_ids))
    missing_visuals = tuple(sorted(set(observed_visual_version_ids) - runtime_visual_ids))
    compatible = not runtime_only and not model_only and not missing_visuals
    return ModelCatalogCompatibility(
        model_id=model_id,
        model_catalog_version=model_catalog_version,
        runtime_catalog_version=snapshot.catalog_version,
        preprocessing_version=preprocessing_version,
        input_size=input_size,
        supported_class_ids=tuple(sorted(model_ids)),
        observed_visual_version_ids=tuple(sorted(observed_visual_version_ids)),
        runtime_only_class_ids=runtime_only,
        model_only_class_ids=model_only,
        missing_observed_visual_version_ids=missing_visuals,
        classifier_compatible=compatible,
        prototype_fallback_required=bool(runtime_only),
    )
