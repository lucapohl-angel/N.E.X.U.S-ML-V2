#!/usr/bin/env python3
"""Export the minimal private inference bundle required by the production API."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tarfile
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "catalogs/staging/user-approved-2026-08-01-r2/catalog.json"
HERO_SOURCE = (
    ROOT
    / "data/private/recognition_prototypes/hero-catalog-batches01-07-v1/hero/manifest.json"
)
ITEM_SOURCE = ROOT / "data/private/recognition_prototypes/family-01-v1/item/manifest.json"
POLICY_SOURCE = ROOT / "data/private/recognition_policies/hero-balanced-v1/policy.json"
HERO_DEST = Path(
    "data/private/recognition_prototypes/hero-catalog-batches01-07-v1/hero/manifest.json"
)
ITEM_DEST = Path("data/private/recognition_prototypes/family-01-v1/item/manifest.json")
POLICY_DEST = Path("data/private/recognition_policies/hero-balanced-v1/policy.json")
CATALOG_DEST = Path("catalogs/staging/user-approved-2026-08-01-r2/catalog.json")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_source(root: Path, relative: str) -> Path:
    resolved = (root / relative).resolve()
    if not resolved.is_relative_to(root.resolve()) or not resolved.is_file():
        raise ValueError(f"unsafe or missing prototype asset: {relative}")
    return resolved


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _export_manifest(
    source_path: Path,
    destination_path: Path,
    *,
    kind: str,
    catalog_names: dict[str, str],
    catalog_sha256: str,
) -> int:
    source: dict[str, Any] = json.loads(source_path.read_text(encoding="utf-8"))
    if source.get("kind") != kind:
        raise ValueError(f"{kind} prototype source has the wrong kind")
    if source.get("catalog_sha256") != catalog_sha256:
        raise ValueError(f"{kind} prototype source does not match the active catalog")

    references: list[dict[str, object]] = []
    destination_root = destination_path.parent
    for index, record in enumerate(source["references"]):
        entity_id = record.get("entity_id")
        if entity_id is not None and str(entity_id) not in catalog_names:
            raise ValueError(f"prototype entity is absent from the catalog: {entity_id}")
        source_asset = _safe_source(source_path.parent, str(record["asset_path"]))
        suffix = source_asset.suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise ValueError(f"unsupported prototype asset type: {source_asset}")
        asset_relative = Path("assets") / f"{kind}_{index:04d}{suffix}"
        destination_asset = destination_root / asset_relative
        destination_asset.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_asset, destination_asset)
        references.append(
            {
                "asset_path": asset_relative.as_posix(),
                "entity_id": None if entity_id is None else str(entity_id),
                "name": record.get("name"),
                "visual_id": str(record["visual_id"]),
            }
        )

    _write_json(
        destination_path,
        {
            "catalog_sha256": catalog_sha256,
            "kind": kind,
            "references": references,
            "schema_version": 1,
        },
    )
    return len(references)


def _minimal_policy(prototype_sha256: str, catalog_sha256: str) -> dict[str, object]:
    source: dict[str, Any] = json.loads(POLICY_SOURCE.read_text(encoding="utf-8"))
    if source.get("catalog_sha256") != catalog_sha256:
        raise ValueError("balanced policy does not match the active catalog")
    return {
        "beta": source["beta"],
        "catalog_sha256": catalog_sha256,
        "enabled": True,
        "gamma": source["gamma"],
        "gate": source["gate"],
        "kind": "constrained_consensus",
        "mode": "balanced",
        "only_abstained": source.get("only_abstained") is True,
        "prototype_manifest_sha256": prototype_sha256,
        "schema_version": 1,
        "status": "operator_approved",
        "top_n": source["top_n"],
    }


def _write_checksums(bundle_root: Path) -> None:
    files = sorted(
        path
        for path in bundle_root.rglob("*")
        if path.is_file() and path.name != "checksums.sha256"
    )
    lines = [f"{_sha256(path)}  {path.relative_to(bundle_root).as_posix()}" for path in files]
    (bundle_root / "checksums.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_bundle(destination: Path) -> None:
    required = (CATALOG, HERO_SOURCE, ITEM_SOURCE, POLICY_SOURCE)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing runtime source assets: " + ", ".join(missing))
    if destination.exists():
        if not destination.is_dir():
            raise ValueError(f"bundle destination is not a directory: {destination}")
        shutil.rmtree(destination)
    destination.mkdir(parents=True)

    catalog_data: dict[str, Any] = json.loads(CATALOG.read_text(encoding="utf-8"))
    catalog_sha256 = _sha256(CATALOG)
    catalog_destination = destination / CATALOG_DEST
    catalog_destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(CATALOG, catalog_destination)
    for entity in (*catalog_data["heroes"], *catalog_data["items"]):
        for visual in entity["visual_versions"]:
            relative = Path(str(visual["asset_path"]))
            source_asset = _safe_source(CATALOG.parent, relative.as_posix())
            destination_asset = catalog_destination.parent / relative
            destination_asset.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_asset, destination_asset)
    hero_names = {str(row["id"]): str(row["canonical_name"]) for row in catalog_data["heroes"]}
    item_names = {str(row["id"]): str(row["canonical_name"]) for row in catalog_data["items"]}
    hero_count = _export_manifest(
        HERO_SOURCE,
        destination / HERO_DEST,
        kind="hero",
        catalog_names=hero_names,
        catalog_sha256=catalog_sha256,
    )
    item_count = _export_manifest(
        ITEM_SOURCE,
        destination / ITEM_DEST,
        kind="item",
        catalog_names=item_names,
        catalog_sha256=catalog_sha256,
    )
    hero_manifest_sha256 = _sha256(destination / HERO_DEST)
    _write_json(
        destination / POLICY_DEST,
        _minimal_policy(hero_manifest_sha256, catalog_sha256),
    )
    _write_json(
        destination / "bundle.json",
        {
            "catalog": CATALOG_DEST.as_posix(),
            "catalog_sha256": catalog_sha256,
            "hero_manifest": HERO_DEST.as_posix(),
            "hero_manifest_sha256": hero_manifest_sha256,
            "hero_references": hero_count,
            "item_manifest": ITEM_DEST.as_posix(),
            "item_manifest_sha256": _sha256(destination / ITEM_DEST),
            "item_references": item_count,
            "policy": POLICY_DEST.as_posix(),
            "policy_sha256": _sha256(destination / POLICY_DEST),
            "schema_version": 1,
        },
    )
    _write_checksums(destination)


def _archive(bundle_root: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    with tarfile.open(temporary, "w:gz") as archive:
        for path in sorted(bundle_root.rglob("*")):
            if path.is_file():
                archive.add(path, arcname=path.relative_to(bundle_root), recursive=False)
    temporary.replace(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    destination = parser.add_mutually_exclusive_group(required=True)
    destination.add_argument("--output-dir", type=Path)
    destination.add_argument("--archive", type=Path)
    args = parser.parse_args()

    if args.output_dir is not None:
        output_dir = args.output_dir.expanduser().resolve()
        build_bundle(output_dir)
        print(output_dir)
        return 0

    archive = args.archive.expanduser().resolve()
    with tempfile.TemporaryDirectory(prefix="nexus-runtime-") as temporary:
        bundle_root = Path(temporary) / "bundle"
        build_bundle(bundle_root)
        _archive(bundle_root, archive)
    print(archive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
