#!/usr/bin/env python3
"""Build capped, side-balanced prototypes from a completed focused visual review batch."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2

from nexus_v2.input import ImageDecoder
from nexus_v2.layout import ProfileRegistry, build_semantic_crops, solve_geometry
from nexus_v2.layout.cropper import SemanticCrop
from nexus_v2.layout.profiles import FieldKind
from nexus_v2.schemas.result import ExtractionStatus

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BATCH = ROOT / "data/private/review_dataset/family-01-hero-catalog-2026-08-02/batch-01"
DEFAULT_CATALOG = ROOT / "catalogs/staging/user-approved-2026-08-01-r2/catalog.json"
DEFAULT_OUTPUT = ROOT / "data/private/recognition_prototypes/hero-catalog-batch01-v1"
SemanticKey = tuple[str, str, str | None, int | None, int | None]
EmptyPlayerKey = tuple[str, str, int]


@dataclass(frozen=True)
class Candidate:
    screenshot: str
    side: str
    row: int
    slot: int | None
    entity_id: str
    crop: SemanticCrop
    source_sha256: str


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def select_balanced(candidates: list[Candidate], cap: int) -> list[Candidate]:
    selected: list[Candidate] = []
    for side in ("ally", "enemy"):
        side_candidates = [candidate for candidate in candidates if candidate.side == side]
        selected.extend(side_candidates[: cap // 2])
    if len(selected) < cap:
        selected_ids = {
            (candidate.screenshot, candidate.side, candidate.row, candidate.slot)
            for candidate in selected
        }
        selected.extend(
            candidate
            for candidate in candidates
            if (candidate.screenshot, candidate.side, candidate.row, candidate.slot)
            not in selected_ids
        )
    return selected[:cap]


def review_truth_required(kind: FieldKind, review_scope: str) -> bool:
    """Require exhaustive truth except for omitted items in active-learning review."""

    return kind is FieldKind.HERO or review_scope != "hero_plus_item_exceptions"


def load_empty_player_rows(
    batch: Path, state_path: Path, state: dict[str, Any]
) -> tuple[set[EmptyPlayerKey], Path | None]:
    """Load hash-bound user-confirmed blank custom-lobby rows, when present."""

    sidecar = batch / ".review/empty_player_rows.review.json"
    if not sidecar.is_file():
        return set(), None
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    if payload.get("truth_sha256") != sha256(state_path):
        raise SystemExit("empty-player sidecar does not match canonical review truth")
    rows: set[EmptyPlayerKey] = set()
    for entry in payload.get("rows", []):
        screenshot = str(entry["screenshot"])
        side = str(entry["side"])
        row = int(entry["row"])
        if side not in {"ally", "enemy"} or row not in range(5):
            raise SystemExit(f"invalid empty-player row: {(screenshot, side, row)}")
        if state["source_hashes"].get(screenshot) != entry.get("source_sha256"):
            raise SystemExit(f"empty-player source hash mismatch: {screenshot}")
        key = (screenshot, side, row)
        if key in rows:
            raise SystemExit(f"duplicate empty-player row: {key}")
        rows.add(key)
    return rows, sidecar


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=Path, default=DEFAULT_BATCH)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--per-class-cap", type=int, default=4)
    parser.add_argument("--version", help="internal immutable prototype version")
    args = parser.parse_args()

    batch = args.batch.resolve()
    catalog_path = args.catalog.resolve()
    output = args.output.resolve()
    private_root = (ROOT / "data/private").resolve()
    if not output.is_relative_to(private_root):
        raise SystemExit("prototype output must remain under data/private")
    if args.per_class_cap < 1:
        raise SystemExit("per-class cap must be positive")
    state_path = batch / ".review/truth.review.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    review_scope = state.get("engine", {}).get("review_scope", "full_match")
    empty_player_rows, empty_player_sidecar = load_empty_player_rows(batch, state_path, state)
    version = args.version or output.name
    unresolved = [
        record["record_id"]
        for record in state["records"]
        if record["kind"] in {"hero", "item"} and record["decision"] in {"pending", "skipped"}
    ]
    if unresolved:
        raise SystemExit(f"visual review is unresolved: {len(unresolved)} records")

    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    names = {
        entity["id"]: entity["canonical_name"]
        for key in ("heroes", "items")
        for entity in catalog[key]
    }
    truth: dict[SemanticKey, dict[str, Any]] = {
        (
            record["screenshot"],
            record["kind"],
            record.get("side"),
            record.get("row"),
            record.get("slot"),
        ): record
        for record in state["records"]
        if record["kind"] in {"hero", "item"}
    }
    if len(truth) != len([r for r in state["records"] if r["kind"] in {"hero", "item"}]):
        raise SystemExit("duplicate semantic review keys")

    registry = ProfileRegistry.load(ROOT / "profiles")
    decoder = ImageDecoder()
    grouped: dict[str, dict[str, list[Candidate]]] = {
        "hero": defaultdict(list),
        "item": defaultdict(list),
    }
    observed_keys: set[SemanticKey] = set()
    observed_empty_player_rows: set[EmptyPlayerKey] = set()
    for screenshot, expected_hash in sorted(state["source_hashes"].items()):
        image_path = batch / screenshot
        if sha256(image_path) != expected_hash:
            raise SystemExit(f"source hash mismatch: {screenshot}")
        image = decoder.decode(image_path)
        geometry = solve_geometry(image, registry)
        if geometry.status is not ExtractionStatus.OK or geometry.profile_id is None:
            raise SystemExit(f"geometry rejected: {screenshot}")
        crops = build_semantic_crops(image, registry.get(geometry.profile_id), geometry)
        for crop in crops:
            if crop.kind not in {FieldKind.HERO, FieldKind.ITEM}:
                continue
            if crop.side is None or crop.row is None:
                raise SystemExit("visual crop lacks side/row identity")
            key = (
                screenshot,
                crop.kind.value,
                crop.side.value,
                crop.row,
                crop.slot,
            )
            record = truth.get(key)
            if record is None:
                if review_truth_required(crop.kind, review_scope):
                    raise SystemExit(f"missing visual truth: {key}")
                continue
            if tuple(record["source_box"]) != crop.tight_box:
                raise SystemExit(f"review/source crop mismatch: {key}")
            observed_keys.add(key)
            entity_id = record["truth_value"]
            if crop.kind is FieldKind.HERO and entity_id is None:
                empty_key = (screenshot, crop.side.value, crop.row)
                if empty_key not in empty_player_rows:
                    raise SystemExit(f"null hero lacks confirmed empty-player evidence: {key}")
                observed_empty_player_rows.add(empty_key)
                continue
            if entity_id is None:
                continue
            grouped[crop.kind.value][entity_id].append(
                Candidate(
                    screenshot=screenshot,
                    side=crop.side.value,
                    row=crop.row,
                    slot=crop.slot,
                    entity_id=entity_id,
                    crop=crop,
                    source_sha256=expected_hash,
                )
            )
    missing = set(truth) - observed_keys
    if missing:
        raise SystemExit(f"review truth has crops not emitted by current geometry: {len(missing)}")
    unused_empty_rows = empty_player_rows - observed_empty_player_rows
    if unused_empty_rows:
        raise SystemExit(
            f"empty-player sidecar rows lack null hero truth: {sorted(unused_empty_rows)}"
        )

    temporary = output.with_name(output.name + ".tmp")
    if temporary.exists():
        shutil.rmtree(temporary)
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing prototype directory: {output}")
    manifests: dict[str, str] = {}
    summaries: dict[str, dict[str, int]] = {}
    for kind in ("hero", "item"):
        references: list[dict[str, Any]] = []
        for entity_id in sorted(grouped[kind]):
            candidates = sorted(
                grouped[kind][entity_id],
                key=lambda candidate: (
                    candidate.side,
                    candidate.screenshot,
                    candidate.row,
                    -1 if candidate.slot is None else candidate.slot,
                ),
            )
            for candidate in select_balanced(candidates, args.per_class_cap):
                index = len(references)
                relative = Path("assets") / f"{kind}_{index:04d}.png"
                target = temporary / kind / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if not cv2.imwrite(
                    str(target), cv2.cvtColor(candidate.crop.tight_rgb, cv2.COLOR_RGB2BGR)
                ):
                    raise SystemExit(f"failed to write prototype: {target}")
                references.append(
                    {
                        "entity_id": entity_id,
                        "name": names[entity_id],
                        "visual_id": f"{version}_{kind}_{index:04d}",
                        "asset_path": relative.as_posix(),
                        "asset_sha256": sha256(target),
                        "source_screenshot": candidate.screenshot,
                        "source_image_sha256": candidate.source_sha256,
                        "source_box": list(candidate.crop.tight_box),
                        "source_side": candidate.side,
                        "source_row": candidate.row,
                        "source_slot": candidate.slot,
                        "calibration_truth_source": "completed_hash_bound_visual_review",
                    }
                )
        manifest_path = temporary / kind / "manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "1.0",
            "prototype_version": version,
            "kind": kind,
            "profile_id": "starter-2026.07-standard",
            "calibration_only": True,
            "evaluation_warning": (
                "Derived from reviewed global-player screenshots. Same-source scores "
                "are calibration, not held-out evidence."
            ),
            "per_class_cap": args.per_class_cap,
            "catalog_sha256": sha256(catalog_path),
            "truth_source_sha256": sha256(state_path),
            "review_scope": review_scope,
            "scoped_item_policy": (
                "explicitly reviewed exceptions only"
                if review_scope == "hero_plus_item_exceptions"
                else "exhaustive visual truth"
            ),
            "source_image_sha256": dict(sorted(state["source_hashes"].items())),
            "excluded_empty_player_rows": [list(key) for key in sorted(empty_player_rows)],
            "empty_player_rows_sidecar_sha256": (
                sha256(empty_player_sidecar) if empty_player_sidecar is not None else None
            ),
            "references": references,
        }
        manifest_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        manifests[kind] = str(output / kind / "manifest.json")
        summaries[kind] = {
            "classes": len(grouped[kind]),
            "available_occupied_crops": sum(len(values) for values in grouped[kind].values()),
            "selected_references": len(references),
        }
    temporary.rename(output)
    print(
        json.dumps(
            {"output": str(output), "manifests": manifests, "summary": summaries}, sort_keys=True
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
