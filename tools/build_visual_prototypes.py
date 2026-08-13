#!/usr/bin/env python3
"""Build private profile-specific visual prototypes from frozen reviewed truth."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import cv2

from nexus_v2.input import ImageDecoder
from nexus_v2.layout import ProfileRegistry, build_semantic_crops, solve_geometry
from nexus_v2.layout.profiles import FieldKind
from nexus_v2.schemas.result import ExtractionStatus

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "data/private/starter_screenshots/frozen/v1"
DEFAULT_CATALOG = ROOT / "catalogs/staging/user-approved-2026-08-01-r2/catalog.json"
DEFAULT_OUTPUT = ROOT / "data/private/recognition_prototypes/starter-v1"
PROFILE_ID = "starter-2026.07-standard"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_manifest(
    root: Path,
    *,
    kind: str,
    references: list[dict[str, Any]],
    dataset_manifest: Path,
    catalog_path: Path,
) -> Path:
    target = root / kind / "manifest.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0",
        "prototype_version": "starter-v1.0",
        "kind": kind,
        "profile_id": PROFILE_ID,
        "calibration_only": True,
        "evaluation_warning": "Derived from the same match; not held-out generalization evidence.",
        "dataset_manifest_sha256": sha256(dataset_manifest),
        "catalog_sha256": sha256(catalog_path),
        "references": references,
    }
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    dataset = args.dataset.resolve()
    catalog_path = args.catalog.resolve()
    output = args.output.resolve()
    private_root = (ROOT / "data/private").resolve()
    if not output.is_relative_to(private_root):
        raise SystemExit("prototype output must remain under data/private")
    manifest_path = dataset / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sample = next(
        record
        for record in manifest["samples"]
        if record["sample_id"] == "hero_item_screen"
    )
    image_path = (dataset / sample["image_path"]).resolve()
    if sha256(image_path) != sample["sha256"]:
        raise SystemExit("frozen prototype source hash mismatch")

    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    hero_names = {entity["id"]: entity["canonical_name"] for entity in catalog["heroes"]}
    item_names = {entity["id"]: entity["canonical_name"] for entity in catalog["items"]}
    truth = sample["annotation"]
    hero_truth = {(record["team"], record["row"]): record for record in truth["heroes"]}
    item_truth = {
        (record["team"], record["row"], record["slot"]): record for record in truth["items"]
    }

    registry = ProfileRegistry.load(ROOT / "profiles")
    loaded = registry.get(PROFILE_ID)
    image = ImageDecoder().decode(image_path)
    geometry = solve_geometry(image, registry)
    if geometry.status is not ExtractionStatus.OK:
        raise SystemExit(f"prototype source geometry rejected: {geometry.reasons}")
    crops = build_semantic_crops(image, loaded, geometry)

    references: dict[str, list[dict[str, Any]]] = {"hero": [], "item": []}
    counters = {"hero": 0, "item": 0}
    for crop in crops:
        if crop.kind not in {FieldKind.HERO, FieldKind.ITEM}:
            continue
        if crop.side is None or crop.row is None:
            raise SystemExit("prototype crop lacks row identity")
        kind = crop.kind.value
        if kind == "hero":
            record = hero_truth[(crop.side.value, crop.row)]
            entity_id = record["stable_id"]
            name = hero_names[entity_id]
        else:
            if crop.slot is None:
                raise SystemExit("item prototype crop lacks slot identity")
            record = item_truth[(crop.side.value, crop.row, crop.slot)]
            entity_id = record.get("stable_id") if record["occupancy"] == "occupied" else None
            name = item_names[entity_id] if entity_id is not None else None
        index = counters[kind]
        counters[kind] += 1
        relative = Path("assets") / f"{kind}_{index:03d}.png"
        target = output / kind / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(target), cv2.cvtColor(crop.tight_rgb, cv2.COLOR_RGB2BGR)):
            raise SystemExit(f"failed to write prototype: {target}")
        references[kind].append(
            {
                "entity_id": entity_id,
                "name": name,
                "visual_id": f"prototype_{kind}_{index:03d}",
                "asset_path": relative.as_posix(),
                "asset_sha256": sha256(target),
                "source_sample_id": sample["sample_id"],
                "source_box": list(crop.tight_box),
            }
        )

    hero_manifest = write_manifest(
        output,
        kind="hero",
        references=references["hero"],
        dataset_manifest=manifest_path,
        catalog_path=catalog_path,
    )
    item_manifest = write_manifest(
        output,
        kind="item",
        references=references["item"],
        dataset_manifest=manifest_path,
        catalog_path=catalog_path,
    )
    print(
        json.dumps(
            {
                "hero_references": len(references["hero"]),
                "item_references": len(references["item"]),
                "hero_manifest": str(hero_manifest),
                "item_manifest": str(item_manifest),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
