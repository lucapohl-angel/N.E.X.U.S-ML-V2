#!/usr/bin/env python3
"""Build private first-family visual prototypes from reviewed, hash-bound truth.

This is calibration data, not holdout evidence. Original review states are never modified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import cv2

from nexus_v2.input import ImageDecoder
from nexus_v2.layout import ProfileRegistry, build_semantic_crops, solve_geometry
from nexus_v2.layout.profiles import FieldKind
from nexus_v2.schemas.result import ExtractionStatus

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FAMILY = ROOT / "data/private/review_dataset/family-01-current-device"
DEFAULT_STARTER = ROOT / "data/private/starter_screenshots/frozen/v1/manifest.json"
DEFAULT_CATALOG = ROOT / "catalogs/staging/user-approved-2026-08-01-r2/catalog.json"
DEFAULT_OUTPUT = ROOT / "data/private/recognition_prototypes/family-01-v1"
GAMES = (
    "game-01-reviewed-starter",
    "game-02",
    "game-03",
    "game-04",
    "game-05",
)
SCREENS = (
    "hero_item_screen.jpeg",
    "overall_screen.jpeg",
    "dps_screen.jpeg",
    "farm_screen.jpeg",
    "team_screen.jpeg",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def starter_truth(path: Path) -> dict[tuple[object, ...], object]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    truth: dict[tuple[object, ...], object] = {}
    for sample in manifest["samples"]:
        screenshot = Path(sample["image_path"]).name
        annotation = sample["annotation"]
        for hero in annotation["heroes"]:
            truth[(screenshot, "hero", hero["team"], hero["row"], None)] = hero["stable_id"]
        for item in annotation["items"]:
            truth[(screenshot, "item", item["team"], item["row"], item["slot"])] = (
                item.get("stable_id") if item["occupancy"] == "occupied" else None
            )
    return truth


def review_truth(
    game_path: Path,
) -> tuple[dict[tuple[object, ...], object], str, list[dict[str, Any]]]:
    state_path = game_path / ".review/truth.review.json"
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    records = payload["records"]
    unresolved = [
        record["record_id"]
        for record in records
        if record["kind"] in {"hero", "item"}
        and record["decision"] in {"pending", "skipped", "unknown"}
    ]
    if unresolved:
        raise ValueError(f"{game_path.name}: unresolved visual truth records: {len(unresolved)}")

    hero_groups: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if record["kind"] == "hero":
            hero_groups[(record["side"], record["row"])].append(record)

    hero_resolution: dict[tuple[str, int], str] = {}
    conflicts: list[dict[str, Any]] = []
    for key, members in hero_groups.items():
        counts = Counter(record["truth_value"] for record in members)
        winner, support = counts.most_common(1)[0]
        if winner is None:
            raise ValueError(f"{game_path.name}: hero truth cannot be empty")
        if len(counts) > 1:
            if support < 4 or len(members) != 5:
                raise ValueError(f"{game_path.name}: ambiguous hero truth conflict at {key}")
            conflicts.append(
                {
                    "game": game_path.name,
                    "side": key[0],
                    "row": key[1],
                    "observed_counts": dict(sorted(counts.items())),
                    "derived_resolution": winner,
                    "support": f"{support}/{len(members)}",
                    "policy": "same-match immutable hero majority; source truth preserved",
                }
            )
        hero_resolution[key] = str(winner)

    truth: dict[tuple[object, ...], object] = {}
    for record in records:
        if record["kind"] == "hero":
            value: object = hero_resolution[(record["side"], record["row"])]
        elif record["kind"] == "item":
            value = record["truth_value"]
        else:
            continue
        truth[
            (
                record["screenshot"],
                record["kind"],
                record.get("side"),
                record.get("row"),
                record.get("slot"),
            )
        ] = value
    return truth, sha256(state_path), conflicts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--family", type=Path, default=DEFAULT_FAMILY)
    parser.add_argument("--starter-manifest", type=Path, default=DEFAULT_STARTER)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--exclude-game", action="append", default=[])
    parser.add_argument(
        "--hero-source-screen",
        action="append",
        choices=SCREENS,
    )
    args = parser.parse_args()

    family = args.family.resolve()
    starter_manifest = args.starter_manifest.resolve()
    catalog_path = args.catalog.resolve()
    output = args.output.resolve()
    private_root = (ROOT / "data/private").resolve()
    if not output.is_relative_to(private_root):
        raise SystemExit("prototype output must remain under data/private")
    excluded = set(args.exclude_game)
    hero_source_screens = set(args.hero_source_screen or SCREENS)
    unknown_exclusions = excluded - set(GAMES)
    if unknown_exclusions:
        raise SystemExit(f"unknown excluded games: {sorted(unknown_exclusions)}")

    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    names = {
        entity["id"]: entity["canonical_name"]
        for key in ("heroes", "items")
        for entity in catalog[key]
    }
    registry = ProfileRegistry.load(ROOT / "profiles")
    decoder = ImageDecoder()
    starter = starter_truth(starter_manifest)
    references: dict[str, list[dict[str, Any]]] = {"hero": [], "item": []}
    state_hashes: dict[str, str] = {}
    source_hashes: dict[str, dict[str, str]] = {}
    conflicts: list[dict[str, Any]] = []

    for game in GAMES:
        if game in excluded:
            continue
        game_path = family / game
        if game == "game-01-reviewed-starter":
            truth = starter
            state_hashes[game] = sha256(starter_manifest)
            game_conflicts: list[dict[str, Any]] = []
        else:
            truth, state_hashes[game], game_conflicts = review_truth(game_path)
        conflicts.extend(game_conflicts)
        source_hashes[game] = {}

        for screenshot in SCREENS:
            image_path = game_path / screenshot
            if not image_path.is_file():
                raise ValueError(f"missing source image: {image_path}")
            image_hash = sha256(image_path)
            source_hashes[game][screenshot] = image_hash
            image = decoder.decode(image_path)
            geometry = solve_geometry(image, registry)
            if geometry.status is not ExtractionStatus.OK or geometry.profile_id is None:
                raise ValueError(f"geometry failed for {game}/{screenshot}: {geometry.reasons}")
            crops = build_semantic_crops(image, registry.get(geometry.profile_id), geometry)
            for crop in crops:
                if crop.kind not in {FieldKind.HERO, FieldKind.ITEM}:
                    continue
                if crop.kind is FieldKind.HERO and screenshot not in hero_source_screens:
                    continue
                if crop.kind is FieldKind.ITEM and screenshot != "hero_item_screen.jpeg":
                    continue
                if crop.side is None or crop.row is None:
                    raise ValueError("visual crop lacks side/row identity")
                kind = crop.kind.value
                key = (
                    screenshot,
                    kind,
                    crop.side.value,
                    crop.row,
                    crop.slot,
                )
                if key not in truth:
                    raise ValueError(f"missing visual truth for {game}: {key}")
                entity_id = truth[key]
                if kind == "hero" and entity_id is None:
                    raise ValueError("hero prototype cannot be empty")
                index = len(references[kind])
                relative = Path("assets") / game / f"{screenshot[:-5]}_{kind}_{index:04d}.png"
                target = output / kind / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                bgr = cv2.cvtColor(crop.tight_rgb, cv2.COLOR_RGB2BGR)
                if not cv2.imwrite(str(target), bgr):
                    raise ValueError(f"failed to write prototype {target}")
                references[kind].append(
                    {
                        "entity_id": entity_id,
                        "name": names.get(entity_id) if entity_id is not None else None,
                        "visual_id": f"family01_{kind}_{index:04d}",
                        "asset_path": relative.as_posix(),
                        "asset_sha256": sha256(target),
                        "source_game": game,
                        "source_screenshot": screenshot,
                        "source_image_sha256": image_hash,
                        "source_box": list(crop.tight_box),
                        "calibration_truth_source": (
                            "frozen_starter_manifest"
                            if game == "game-01-reviewed-starter"
                            else "review_truth_with_same_match_consistency"
                        ),
                    }
                )

    manifests: dict[str, str] = {}
    for kind in ("hero", "item"):
        target = output / kind / "manifest.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "1.0",
            "prototype_version": "family-01-v1.0",
            "kind": kind,
            "profile_id": "starter-2026.07-standard",
            "calibration_only": True,
            "evaluation_warning": (
                "Derived from reviewed first-family games. Same-game/all-family scores are not "
                "held-out generalization evidence."
            ),
            "included_games": [game for game in GAMES if game not in excluded],
            "excluded_games": sorted(excluded),
            "hero_source_screens": sorted(hero_source_screens),
            "catalog_sha256": sha256(catalog_path),
            "truth_source_sha256": state_hashes,
            "source_image_sha256": source_hashes,
            "truth_conflicts": conflicts,
            "references": references[kind],
        }
        target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        manifests[kind] = str(target)

    print(
        json.dumps(
            {
                "hero_references": len(references["hero"]),
                "item_references": len(references["item"]),
                "truth_conflicts": len(conflicts),
                "manifests": manifests,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
