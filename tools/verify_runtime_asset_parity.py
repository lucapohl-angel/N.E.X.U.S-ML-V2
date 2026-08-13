#!/usr/bin/env python3
"""Verify that an exported runtime bundle preserves production recognition inputs exactly."""

from __future__ import annotations

import argparse
import hashlib
from dataclasses import asdict
from pathlib import Path

import numpy as np

from nexus_v2.recognition import ReferenceLibrary
from nexus_v2.recognition.modes import resolve_hero_recognition, resolve_item_recognition

ROOT = Path(__file__).resolve().parents[1]
CATALOG_RELATIVE = Path("catalogs/staging/user-approved-2026-08-01-r2/catalog.json")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_library_parity(
    source: ReferenceLibrary,
    exported: ReferenceLibrary,
    *,
    kind: str,
) -> None:
    if len(source.references) != len(exported.references):
        raise AssertionError(f"{kind} reference count changed")
    for index, (left, right) in enumerate(zip(source.references, exported.references, strict=True)):
        left_meta = (left.entity_id, left.name, left.visual_id, left.source)
        right_meta = (right.entity_id, right.name, right.visual_id, right.source)
        if left_meta != right_meta:
            raise AssertionError(f"{kind} reference metadata changed at index {index}")
        if not np.array_equal(left.image, right.image):
            raise AssertionError(f"{kind} reference pixels changed at index {index}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runtime_assets", type=Path)
    args = parser.parse_args()
    exported_root = args.runtime_assets.expanduser().resolve()
    source_catalog = ROOT / CATALOG_RELATIVE
    exported_catalog = exported_root / CATALOG_RELATIVE
    if _sha256(source_catalog) != _sha256(exported_catalog):
        raise AssertionError("catalog bytes changed in the runtime export")

    source_hero = resolve_hero_recognition(
        project_root=ROOT,
        catalog_path=source_catalog,
        mode="balanced",
    )
    exported_hero = resolve_hero_recognition(
        project_root=exported_root,
        catalog_path=exported_catalog,
        mode="balanced",
    )
    if asdict(source_hero.matcher_config) != asdict(exported_hero.matcher_config):
        source_config = asdict(source_hero.matcher_config)
        exported_config = asdict(exported_hero.matcher_config)
        source_policy = source_config.pop("hero_balanced_policy")
        exported_policy = exported_config.pop("hero_balanced_policy")
        if source_config != exported_config:
            raise AssertionError("exported matcher configuration changed")
        policy_fields = (
            "schema_version",
            "beta",
            "gamma",
            "top_n",
            "only_abstained",
            "minimum_prototype",
            "minimum_rank_margin",
            "minimum_prototype_margin",
            "minimum_votes",
            "catalog_sha256",
        )
        if source_policy is None or exported_policy is None or any(
            source_policy[field] != exported_policy[field] for field in policy_fields
        ):
            raise AssertionError("exported balanced policy behavior changed")

    source_item = resolve_item_recognition(project_root=ROOT, catalog_path=source_catalog)
    exported_item = resolve_item_recognition(
        project_root=exported_root,
        catalog_path=exported_catalog,
    )
    _assert_library_parity(
        ReferenceLibrary.load(
            source_catalog,
            kind="hero",
            prototype_manifest=source_hero.prototype_manifest,
        ),
        ReferenceLibrary.load(
            exported_catalog,
            kind="hero",
            prototype_manifest=exported_hero.prototype_manifest,
        ),
        kind="hero",
    )
    _assert_library_parity(
        ReferenceLibrary.load(
            source_catalog,
            kind="item",
            prototype_manifest=source_item.prototype_manifest,
        ),
        ReferenceLibrary.load(
            exported_catalog,
            kind="item",
            prototype_manifest=exported_item.prototype_manifest,
        ),
        kind="item",
    )
    print("runtime recognition parity verified: catalog, policies, metadata, and pixels identical")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
