"""Catalog synchronization, diffing, class-map generation, and promotion."""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TypeAlias

from nexus_v2.catalog.audit import audit_snapshot
from nexus_v2.catalog.images import (
    AssetValidationError,
    SafeImageDownloader,
    ValidatedImage,
    phash_distance,
    safe_asset_destination,
    validate_local_image,
)
from nexus_v2.catalog.models import (
    AssetProvenance,
    CatalogDiff,
    CatalogKind,
    CatalogMigrationReport,
    CatalogSnapshot,
    CatalogSyncReport,
    ClassMapEntry,
    HeroRecord,
    ItemRecord,
    MigrationMapping,
    MigrationStatus,
    ProvenanceStatus,
    ReviewStatus,
    SnapshotStatus,
    SourceFailure,
    VisualVersion,
)
from nexus_v2.catalog.sources import CatalogSource, SourceCandidate, normalize_label
from nexus_v2.catalog.storage import (
    CatalogStorageError,
    load_snapshot,
    write_immutable_snapshot,
    write_json,
)

CatalogRecord: TypeAlias = HeroRecord | ItemRecord
_STABLE_ID_NAMESPACE = uuid.UUID("d8141574-300b-48fd-9676-a18202f8cd68")


class CatalogSyncError(RuntimeError):
    """Raised when no valid immutable staging snapshot can be produced."""


@dataclass(frozen=True)
class SyncArtifacts:
    snapshot: CatalogSnapshot
    snapshot_sha256: str
    snapshot_path: Path
    sync_report: CatalogSyncReport
    migration_report: CatalogMigrationReport
    diff: CatalogDiff | None


@dataclass(frozen=True)
class _ResolvedAsset:
    candidate: SourceCandidate
    image: ValidatedImage


def _records(snapshot: CatalogSnapshot) -> tuple[CatalogRecord, ...]:
    return (*snapshot.heroes, *snapshot.items)


def _stable_id(candidate: SourceCandidate, used_ids: set[str]) -> str:
    if candidate.kind is CatalogKind.HERO:
        numeric_match = candidate.source_identity.rsplit(":", 1)[-1]
        if numeric_match.isdigit():
            base = f"hero_{int(numeric_match):04d}"
        else:
            digest = uuid.uuid5(
                _STABLE_ID_NAMESPACE,
                f"hero:{candidate.source_adapter}:{candidate.source_identity}",
            ).hex
            base = f"hero_{digest[:12]}"
    elif normalize_label(candidate.canonical_name) == "empty slot":
        base = "item_empty_slot"
    else:
        digest = uuid.uuid5(
            _STABLE_ID_NAMESPACE,
            f"item:{candidate.source_adapter}:{candidate.source_identity}",
        ).hex
        base = f"item_{digest[:12]}"
    candidate_id = base
    suffix = 2
    while candidate_id in used_ids:
        candidate_id = f"{base}_{suffix}"
        suffix += 1
    return candidate_id


def _previous_indices(snapshot: CatalogSnapshot | None, kind: CatalogKind) -> dict[str, int]:
    if snapshot is None:
        return {}
    entries = snapshot.hero_class_map if kind is CatalogKind.HERO else snapshot.item_class_map
    return {entry.stable_id: entry.index for entry in entries}


def generate_class_map(
    record_ids: set[str], previous_indices: dict[str, int]
) -> tuple[ClassMapEntry, ...]:
    """Keep every surviving index order and append new stable IDs deterministically."""

    surviving = sorted(
        (stable_id for stable_id in record_ids if stable_id in previous_indices),
        key=previous_indices.__getitem__,
    )
    appended = sorted(record_ids - set(surviving))
    return tuple(
        ClassMapEntry(index=index, stable_id=stable_id)
        for index, stable_id in enumerate((*surviving, *appended))
    )


def catalog_diff(old: CatalogSnapshot, new: CatalogSnapshot) -> CatalogDiff:
    old_records = {record.id: record for record in _records(old)}
    new_records = {record.id: record for record in _records(new)}
    old_ids = set(old_records)
    new_ids = set(new_records)
    common = old_ids & new_ids
    renamed = {
        stable_id: (
            old_records[stable_id].canonical_name,
            new_records[stable_id].canonical_name,
        )
        for stable_id in sorted(common)
        if old_records[stable_id].canonical_name != new_records[stable_id].canonical_name
    }
    changed_visuals = tuple(
        stable_id
        for stable_id in sorted(common)
        if {visual.sha256 for visual in old_records[stable_id].visual_versions}
        != {visual.sha256 for visual in new_records[stable_id].visual_versions}
    )
    old_map = {entry.stable_id: entry.index for entry in (*old.hero_class_map, *old.item_class_map)}
    new_map = {entry.stable_id: entry.index for entry in (*new.hero_class_map, *new.item_class_map)}
    class_map_changes = {
        stable_id: (old_map.get(stable_id), new_map.get(stable_id))
        for stable_id in sorted(set(old_map) | set(new_map))
        if old_map.get(stable_id) != new_map.get(stable_id)
    }
    changed_set = set(changed_visuals) | set(renamed)
    return CatalogDiff(
        old_catalog_version=old.catalog_version,
        new_catalog_version=new.catalog_version,
        added_class_ids=tuple(sorted(new_ids - old_ids)),
        removed_class_ids=tuple(sorted(old_ids - new_ids)),
        renamed_classes=renamed,
        changed_visual_classes=changed_visuals,
        unchanged_class_ids=tuple(sorted(common - changed_set)),
        class_map_changes=class_map_changes,
    )


def _candidate_previous_matches(
    asset: _ResolvedAsset,
    previous: CatalogSnapshot | None,
) -> tuple[CatalogRecord, ...]:
    if previous is None:
        return ()
    candidates = [
        record
        for record in _records(previous)
        if (record.id.startswith("hero_")) == (asset.candidate.kind is CatalogKind.HERO)
    ]
    identity_matches = [
        record
        for record in candidates
        if any(
            visual.provenance.source_identity == asset.candidate.source_identity
            for visual in record.visual_versions
        )
    ]
    if identity_matches:
        return tuple(identity_matches)
    hash_matches = [
        record
        for record in candidates
        if any(visual.sha256 == asset.image.sha256 for visual in record.visual_versions)
    ]
    if hash_matches:
        return tuple(hash_matches)
    label = normalize_label(asset.candidate.canonical_name)
    label_matches = []
    for record in candidates:
        known_labels = {normalize_label(record.canonical_name)}
        known_labels.update(
            normalize_label(alias) for aliases in record.aliases.values() for alias in aliases
        )
        if label in known_labels:
            label_matches.append(record)
    return tuple(label_matches)


def _copy_previous_visuals(
    record: CatalogRecord,
    previous_root: Path,
    target_root: Path,
    failures: list[SourceFailure],
) -> tuple[VisualVersion, ...]:
    copied: list[VisualVersion] = []
    for visual in record.visual_versions:
        source = previous_root / visual.asset_path
        target = target_root / visual.asset_path
        try:
            validated = validate_local_image(source)
            if validated.sha256 != visual.sha256:
                raise AssetValidationError("previous snapshot asset failed its manifest SHA-256")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            copied.append(visual)
        except (AssetValidationError, OSError) as exc:
            failures.append(
                SourceFailure(
                    source_adapter="previous_snapshot",
                    source_identity=visual.id,
                    stage="copy",
                    reason=str(exc),
                )
            )
    return tuple(copied)


def _visual_for_asset(
    stable_id: str,
    asset: _ResolvedAsset,
    target_root: Path,
    retrieved_at: datetime,
) -> VisualVersion:
    visual_id = f"{stable_id}_visual_{asset.image.sha256[:12]}"
    kind_directory = "heroes" if asset.candidate.kind is CatalogKind.HERO else "items"
    destination = safe_asset_destination(
        target_root,
        kind_directory,
        stable_id,
        visual_id,
        asset.image.suffix,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(asset.image.content)
    relative = destination.relative_to(target_root).as_posix()
    method = "local_migration" if asset.candidate.local_path is not None else "https_download"
    return VisualVersion(
        id=visual_id,
        asset_path=relative,
        sha256=asset.image.sha256,
        phash=asset.image.phash,
        width=asset.image.width,
        height=asset.image.height,
        mime_type=asset.image.mime_type,
        review_status=ReviewStatus.UNREVIEWED,
        provenance=AssetProvenance(
            source_adapter=asset.candidate.source_adapter,
            source_identity=asset.candidate.source_identity,
            source_reference=asset.candidate.source_reference,
            retrieved_at=retrieved_at,
            retrieval_method=method,
            status=ProvenanceStatus.UNVERIFIED,
            credential_environment_variables=asset.candidate.credential_environment_variables,
            notes=asset.candidate.notes,
        ),
    )


def _record_for_asset(
    stable_id: str,
    asset: _ResolvedAsset,
    previous_record: CatalogRecord | None,
    previous_root: Path | None,
    target_root: Path,
    retrieved_at: datetime,
    failures: list[SourceFailure],
) -> tuple[CatalogRecord, bool]:
    previous_visuals: tuple[VisualVersion, ...] = ()
    if previous_record is not None and previous_root is not None:
        previous_visuals = _copy_previous_visuals(
            previous_record, previous_root, target_root, failures
        )
    same_visual = next(
        (visual for visual in previous_visuals if visual.sha256 == asset.image.sha256), None
    )
    visual_changed = previous_record is not None and same_visual is None
    if same_visual is None:
        current_visual = _visual_for_asset(stable_id, asset, target_root, retrieved_at)
        visuals = (*previous_visuals, current_visual)
    else:
        visuals = previous_visuals
    renamed = (
        previous_record is not None
        and previous_record.canonical_name != asset.candidate.canonical_name
    )
    if previous_record is None:
        review_status = ReviewStatus.UNREVIEWED
    elif visual_changed or renamed:
        review_status = ReviewStatus.CHANGES_PENDING
    else:
        review_status = previous_record.review_status
    aliases = dict(asset.candidate.aliases)
    if previous_record is not None:
        for locale, values in previous_record.aliases.items():
            aliases[locale] = tuple(dict.fromkeys((*values, *aliases.get(locale, ()))))
        if previous_record.canonical_name != asset.candidate.canonical_name:
            aliases["en"] = tuple(
                dict.fromkeys((*aliases.get("en", ()), previous_record.canonical_name))
            )
    if asset.candidate.kind is CatalogKind.HERO:
        return (
            HeroRecord(
                id=stable_id,
                canonical_name=asset.candidate.canonical_name,
                aliases=aliases,
                active_from_patch=(
                    previous_record.active_from_patch if previous_record is not None else None
                ),
                active_until_patch=None,
                review_status=review_status,
                visual_versions=visuals,
            ),
            visual_changed,
        )
    return (
        ItemRecord(
            id=stable_id,
            canonical_name=asset.candidate.canonical_name,
            aliases=aliases,
            active_from_patch=(
                previous_record.active_from_patch if previous_record is not None else None
            ),
            active_until_patch=None,
            review_status=review_status,
            classification_enabled=asset.candidate.classification_enabled,
            visual_versions=visuals,
        ),
        visual_changed,
    )


def _retrieve_assets(
    sources: tuple[CatalogSource, ...], downloader: SafeImageDownloader
) -> tuple[list[_ResolvedAsset], list[SourceFailure], int, int]:
    assets: list[_ResolvedAsset] = []
    failures: list[SourceFailure] = []
    hero_candidates = 0
    item_candidates = 0
    for source in sources:
        try:
            result = source.discover()
        except Exception as exc:  # defensive adapter isolation boundary
            failures.append(
                SourceFailure(
                    source_adapter=source.adapter_id,
                    stage="discovery",
                    reason=f"source adapter failed: {type(exc).__name__}: {exc}",
                )
            )
            continue
        failures.extend(result.failures)
        for candidate in result.candidates:
            if candidate.kind is CatalogKind.HERO:
                hero_candidates += 1
            else:
                item_candidates += 1
            try:
                if candidate.local_path is not None:
                    image = validate_local_image(candidate.local_path)
                elif candidate.asset_url is not None:
                    image = downloader.download(
                        candidate.asset_url,
                        allowed_hosts=candidate.allowed_asset_hosts,
                    )
                else:
                    raise AssetValidationError("candidate omitted an asset location")
                assets.append(_ResolvedAsset(candidate=candidate, image=image))
            except (AssetValidationError, OSError, RuntimeError) as exc:
                failures.append(
                    SourceFailure(
                        source_adapter=candidate.source_adapter,
                        source_identity=candidate.source_identity,
                        stage="download" if candidate.asset_url else "validation",
                        reason=str(exc),
                    )
                )
    return assets, failures, hero_candidates, item_candidates


def _duplicate_groups(
    records: tuple[CatalogRecord, ...], *, near: bool
) -> tuple[tuple[str, ...], ...]:
    visuals = [
        (record.id, visual.id, visual.sha256, visual.phash)
        for record in records
        for visual in record.visual_versions
    ]
    groups: set[tuple[str, ...]] = set()
    for index, (left_class, left_id, left_sha, left_phash) in enumerate(visuals):
        for right_class, right_id, right_sha, right_phash in visuals[index + 1 :]:
            if left_class == right_class:
                continue
            is_match = (
                left_sha != right_sha and phash_distance(left_phash, right_phash) <= 4
                if near
                else left_sha == right_sha
            )
            if is_match:
                groups.add(tuple(sorted((left_id, right_id))))
    return tuple(sorted(groups))


def sync_catalog(
    *,
    sources: tuple[CatalogSource, ...],
    staging_path: Path,
    catalog_version: str,
    previous_path: Path | None = None,
    downloader: SafeImageDownloader | None = None,
) -> SyncArtifacts:
    """Build one immutable snapshot without modifying a previous or V1 asset tree."""

    if staging_path.exists():
        raise CatalogSyncError(f"staging path already exists: {staging_path}")
    previous: CatalogSnapshot | None = None
    previous_digest: str | None = None
    previous_root: Path | None = None
    if previous_path is not None:
        try:
            previous, previous_digest, previous_manifest = load_snapshot(previous_path)
        except CatalogStorageError as exc:
            raise CatalogSyncError(str(exc)) from exc
        previous_root = previous_manifest.parent
    retrieved_at = datetime.now(timezone.utc)
    assets, failures, hero_candidates, item_candidates = _retrieve_assets(
        sources, downloader or SafeImageDownloader()
    )
    staging_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(
        tempfile.mkdtemp(prefix=f".{staging_path.name}.", dir=staging_path.parent)
    )
    mappings: list[MigrationMapping] = []
    changed_ids: list[str] = []
    try:
        used_ids = {record.id for record in _records(previous)} if previous is not None else set()
        new_records: list[CatalogRecord] = []
        seen_previous_ids: set[str] = set()
        source_identity_groups: dict[tuple[CatalogKind, str], list[_ResolvedAsset]] = defaultdict(
            list
        )
        for asset in assets:
            source_identity_groups[(asset.candidate.kind, asset.candidate.source_identity)].append(
                asset
            )
        ambiguous_assets = {
            id(asset)
            for group in source_identity_groups.values()
            if len(group) > 1
            for asset in group
        }
        for asset in sorted(
            assets,
            key=lambda value: (
                value.candidate.kind.value,
                value.candidate.source_adapter,
                value.candidate.source_identity,
                value.image.sha256,
            ),
        ):
            candidate = asset.candidate
            if (
                candidate.kind is CatalogKind.ITEM
                and not candidate.classification_enabled
                and normalize_label(candidate.canonical_name) == "empty slot"
            ):
                mappings.append(
                    MigrationMapping(
                        legacy_path=candidate.legacy_path or candidate.source_reference,
                        kind=candidate.kind,
                        source_identity=candidate.source_identity,
                        stable_id="item_empty_slot",
                        status=MigrationStatus.MAPPED_UNREVIEWED,
                        match_basis="excluded_empty_slot_sentinel",
                        notes=(
                            *candidate.notes,
                            "mapped as slot state, not an item identity or production asset",
                        ),
                    )
                )
                continue
            if id(asset) in ambiguous_assets:
                related = tuple(
                    sorted(
                        group_asset.candidate.legacy_path or group_asset.candidate.source_reference
                        for group_asset in source_identity_groups[
                            (candidate.kind, candidate.source_identity)
                        ]
                    )
                )
                mappings.append(
                    MigrationMapping(
                        legacy_path=candidate.legacy_path or candidate.source_reference,
                        kind=candidate.kind,
                        source_identity=candidate.source_identity,
                        status=MigrationStatus.AMBIGUOUS,
                        ambiguity_candidates=related,
                        notes=("duplicate source identity; no class mapping was guessed",),
                    )
                )
                continue
            matches = _candidate_previous_matches(asset, previous)
            if len(matches) > 1:
                mappings.append(
                    MigrationMapping(
                        legacy_path=candidate.legacy_path or candidate.source_reference,
                        kind=candidate.kind,
                        source_identity=candidate.source_identity,
                        status=MigrationStatus.AMBIGUOUS,
                        ambiguity_candidates=tuple(sorted(record.id for record in matches)),
                        notes=("multiple previous classes matched; no mapping was guessed",),
                    )
                )
                continue
            previous_record = matches[0] if matches else None
            if previous_record is not None and previous_record.id in seen_previous_ids:
                mappings.append(
                    MigrationMapping(
                        legacy_path=candidate.legacy_path or candidate.source_reference,
                        kind=candidate.kind,
                        source_identity=candidate.source_identity,
                        status=MigrationStatus.AMBIGUOUS,
                        ambiguity_candidates=(previous_record.id,),
                        notes=("multiple source records matched one class; no merge was guessed",),
                    )
                )
                continue
            stable_id = (
                previous_record.id
                if previous_record is not None
                else _stable_id(candidate, used_ids)
            )
            used_ids.add(stable_id)
            if previous_record is not None:
                seen_previous_ids.add(previous_record.id)
                match_basis = "previous_source_identity_or_asset"
            else:
                match_basis = "new_stable_id_assignment"
            record, visual_changed = _record_for_asset(
                stable_id,
                asset,
                previous_record,
                previous_root,
                temporary_root,
                retrieved_at,
                failures,
            )
            new_records.append(record)
            if visual_changed:
                changed_ids.append(stable_id)
            mappings.append(
                MigrationMapping(
                    legacy_path=candidate.legacy_path or candidate.source_reference,
                    kind=candidate.kind,
                    source_identity=candidate.source_identity,
                    stable_id=stable_id,
                    status=MigrationStatus.MAPPED_UNREVIEWED,
                    match_basis=match_basis,
                    notes=candidate.notes,
                )
            )
        for failure in failures:
            if failure.source_identity is not None and not any(
                mapping.source_identity == failure.source_identity for mapping in mappings
            ):
                mappings.append(
                    MigrationMapping(
                        legacy_path=failure.source_identity,
                        kind=(
                            CatalogKind.HERO
                            if "hero" in failure.source_identity.casefold()
                            else CatalogKind.ITEM
                        ),
                        source_identity=failure.source_identity,
                        status=MigrationStatus.FAILED,
                        notes=(failure.reason,),
                    )
                )
        heroes = tuple(
            sorted(
                (record for record in new_records if isinstance(record, HeroRecord)),
                key=lambda record: record.id,
            )
        )
        items = tuple(
            sorted(
                (record for record in new_records if isinstance(record, ItemRecord)),
                key=lambda record: record.id,
            )
        )
        hero_map = generate_class_map(
            {record.id for record in heroes},
            _previous_indices(previous, CatalogKind.HERO),
        )
        item_map = generate_class_map(
            {record.id for record in items if record.classification_enabled},
            _previous_indices(previous, CatalogKind.ITEM),
        )
        snapshot = CatalogSnapshot(
            catalog_version=catalog_version,
            generated_at=retrieved_at,
            status=SnapshotStatus.STAGING,
            previous_snapshot_sha256=previous_digest,
            heroes=heroes,
            items=items,
            hero_class_map=hero_map,
            item_class_map=item_map,
        )
        digest = write_immutable_snapshot(temporary_root, snapshot)
        migration = CatalogMigrationReport(
            catalog_version=catalog_version,
            generated_at=retrieved_at,
            hero_files_discovered=hero_candidates,
            item_files_discovered=item_candidates,
            mapped_files=sum(
                mapping.status is MigrationStatus.MAPPED_UNREVIEWED for mapping in mappings
            ),
            ambiguous_files=sum(
                mapping.status is MigrationStatus.AMBIGUOUS for mapping in mappings
            ),
            failed_files=sum(mapping.status is MigrationStatus.FAILED for mapping in mappings),
            mappings=tuple(sorted(mappings, key=lambda mapping: mapping.legacy_path)),
        )
        difference = catalog_diff(previous, snapshot) if previous is not None else None
        sync_report = CatalogSyncReport(
            catalog_version=catalog_version,
            generated_at=retrieved_at,
            snapshot_path=str(staging_path),
            snapshot_sha256=digest,
            hero_candidates=hero_candidates,
            item_candidates=item_candidates,
            added_classes=(
                difference.added_class_ids
                if difference is not None
                else tuple(record.id for record in _records(snapshot))
            ),
            changed_visual_classes=tuple(sorted(changed_ids)),
            failed_downloads=tuple(failures),
            exact_duplicate_groups=_duplicate_groups(_records(snapshot), near=False),
            near_duplicate_groups=_duplicate_groups(_records(snapshot), near=True),
        )
        write_json(temporary_root / "migration_report.json", migration.model_dump(mode="json"))
        write_json(temporary_root / "sync_report.json", sync_report.model_dump(mode="json"))
        if difference is not None:
            write_json(temporary_root / "diff.json", difference.model_dump(mode="json"))
        audit = audit_snapshot(snapshot, temporary_root)
        write_json(temporary_root / "audit_report.json", audit.model_dump(mode="json"))
        os.replace(temporary_root, staging_path)
        return SyncArtifacts(
            snapshot=snapshot,
            snapshot_sha256=digest,
            snapshot_path=staging_path,
            sync_report=sync_report,
            migration_report=migration,
            diff=difference,
        )
    except (OSError, CatalogStorageError, ValueError) as exc:
        shutil.rmtree(temporary_root, ignore_errors=True)
        if isinstance(exc, CatalogSyncError):
            raise
        raise CatalogSyncError(str(exc)) from exc
