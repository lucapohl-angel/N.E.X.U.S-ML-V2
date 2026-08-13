#!/usr/bin/env python3
"""Compile the human-corrected starter TXT files into a private benchmark manifest.

The source TXT files are treated as immutable. Parenthetical reviewer corrections such as
``(its eudora)`` and ``(should be war axe)`` override the draft value without rewriting the
source. Generated manifests stay under the ignored private dataset directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image

from nexus_v2.schemas.annotation import AnnotationManifest

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "data/private/starter_screenshots/frozen/v1"
DEFAULT_CATALOG = ROOT / "catalogs/staging/user-approved-2026-08-01-r2/catalog.json"
MATCH_GROUP_ID = "starter-match-2026-07-31"
VIEWPORT = (0, 150, 1600, 1050)
ROW_TOPS = (335, 451, 567, 683, 799)
ROW_HEIGHT = 116

SCREEN_FILES = {
    "hero_item_screen": ("hero_item_build", "screen1"),
    "overall_screen": ("overall", "screen2"),
    "dps_screen": ("dps", "screen3"),
    "farm_screen": ("farm", "screen4"),
    "team_screen": ("team", "screen5"),
}

SKIP_KEYS = {
    "annotation_method",
    "battle_id_note",
    "headers",
    "hero_confidence",
    "hero_note",
    "human_approved",
    "layout",
    "name_confidence",
    "name_note",
    "review_status",
    "row",
    "screen_type",
    "source_file",
    "source_resolution",
    "warning",
}

INT_FIELDS = {
    "assists",
    "consecutive_kills",
    "crowd_control",
    "damage_taken",
    "deaths",
    "enemy_kills",
    "healing_and_shields",
    "hero_damage",
    "jungle_gold",
    "kill_gold",
    "kills",
    "level",
    "minion_gold",
    "team_kills",
    "total_gold",
    "turret_damage",
}

PERCENT_FIELDS = {
    "crowd_control_percent",
    "damage_taken_percent",
    "healing_and_shields_percent",
    "hero_damage_percent",
    "jungle_gold_percent",
    "kill_gold_percent",
    "minion_gold_percent",
    "teamfight_participation",
    "total_gold_percent",
    "turret_damage_percent",
}

FIELD_ALIASES = {
    "hp_regen": "healing_and_shields",
    "hp_regen_percent": "healing_and_shields_percent",
    "gold": "total_gold",
    "name": "player_name",
}

CORRECTION_PATTERNS = (
    re.compile(r"\(\s*(?:human\s+proof\s*:\s*)?its\s+([^)]+)\s*\)", re.IGNORECASE),
    re.compile(r"\(\s*should\s+be\s+([^)]+)\s*\)", re.IGNORECASE),
)


@dataclass(frozen=True)
class ParsedTruth:
    metadata: dict[str, str]
    match: dict[str, str]
    players: dict[str, list[dict[str, str]]]


def normalize_label(value: str) -> str:
    folded = value.casefold().replace("’", "'")
    return " ".join(re.sub(r"[^\w]+", " ", folded, flags=re.UNICODE).split())


def clean_reviewed_value(raw: str) -> str:
    for pattern in CORRECTION_PATTERNS:
        matches = list(pattern.finditer(raw))
        if matches:
            return matches[-1].group(1).strip().rstrip(".)")
    value = raw.split("(", 1)[0].strip()
    value = re.sub(r"\s*\[[^\]]*\]\s*$", "", value).strip()
    return value


def parse_truth(path: Path) -> ParsedTruth:
    metadata: dict[str, str] = {}
    match: dict[str, str] = {}
    players: dict[str, list[dict[str, str]]] = {"ally": [], "enemy": []}
    current: dict[str, str] = metadata

    for source_line in path.read_text(encoding="utf-8").splitlines():
        line = source_line.strip()
        if not line or line == "NEXUS_ML_V2_STARTER_TRUTH_DRAFT":
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            if section == "MATCH":
                current = match
                continue
            player_match = re.fullmatch(r"(ALLY|ENEMY)_PLAYER_(\d+)", section)
            if player_match is None:
                raise ValueError(f"unsupported section {section!r} in {path}")
            side = player_match.group(1).casefold()
            current = {"row": str(int(player_match.group(2)) - 1)}
            players[side].append(current)
            continue
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        cleaned = clean_reviewed_value(raw.strip())
        current[key.strip()] = cleaned

    for side in ("ally", "enemy"):
        if len(players[side]) != 5:
            raise ValueError(f"{path.name}: expected five {side} rows, got {len(players[side])}")
        for row_index, player in enumerate(players[side]):
            player["row"] = str(row_index)
    return ParsedTruth(metadata=metadata, match=match, players=players)


def scalar(field: str, value: str) -> str | int | float:
    if field in INT_FIELDS:
        return int(value.replace(" ", ""))
    if field in PERCENT_FIELDS:
        return int(value.rstrip("% "))
    if field == "rating":
        return float(value)
    return value


def catalog_index(
    catalog_path: Path,
) -> tuple[dict[str, tuple[str, str]], dict[str, tuple[str, str]]]:
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    result: list[dict[str, tuple[str, str]]] = []
    for records in (payload["heroes"], payload["items"]):
        index: dict[str, tuple[str, str]] = {}
        for record in records:
            names = {record["canonical_name"]}
            for aliases in record.get("aliases", {}).values():
                names.update(aliases)
            for name in names:
                index[normalize_label(name)] = (record["id"], record["canonical_name"])
        result.append(index)
    return result[0], result[1]


def lookup(
    raw_name: str,
    index: dict[str, tuple[str, str]],
    *,
    kind: str,
    source: str,
) -> tuple[str, str]:
    key = normalize_label(raw_name)
    match = index.get(key)
    if match is None:
        raise ValueError(f"{source}: corrected {kind} {raw_name!r} is absent from approved catalog")
    return match


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_annotation(
    parsed: ParsedTruth,
    semantic_screen: str,
    schema_screen: str,
    hero_index: dict[str, tuple[str, str]],
    item_index: dict[str, tuple[str, str]],
    *,
    source_name: str,
) -> dict[str, Any]:
    heroes: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    fields: list[dict[str, Any]] = []
    semantic_teams: dict[str, list[dict[str, Any]]] = {"ally": [], "enemy": []}

    for key, raw in parsed.match.items():
        if key in SKIP_KEYS:
            continue
        field = FIELD_ALIASES.get(key, key)
        fields.append(
            {
                "field": field,
                "value": scalar(field, raw),
                "status": "ok",
                "critical": field in {"result", "team_kills", "enemy_kills", "duration"},
            }
        )

    for side in ("ally", "enemy"):
        for player in parsed.players[side]:
            row = int(player["row"])
            hero_raw = player.get("hero")
            if hero_raw is None:
                raise ValueError(f"{source_name}: missing hero for {side} row {row + 1}")
            hero_id, hero_name = lookup(
                hero_raw, hero_index, kind="hero", source=f"{source_name}:{side}:{row + 1}"
            )
            heroes.append(
                {
                    "team": side,
                    "row": row,
                    "stable_id": hero_id,
                    "unknown": False,
                    "critical": True,
                }
            )
            semantic_player: dict[str, Any] = {"row": row + 1, "hero": hero_name}

            for key, raw in player.items():
                if key == "row" or key in SKIP_KEYS or key == "hero" or key.startswith("item"):
                    continue
                field = FIELD_ALIASES.get(key, key)
                value = scalar(field, raw)
                fields.append(
                    {
                        "field": field,
                        "value": value,
                        "status": "ok",
                        "team": side,
                        "row": row,
                        "critical": field in {"player_name", "kills", "deaths", "assists"},
                    }
                )
                semantic_player[field] = value

            if semantic_screen == "hero_item_build":
                semantic_items: list[str | None] = []
                for slot in range(6):
                    raw = player.get(f"item{slot + 1}")
                    if raw is None:
                        raise ValueError(
                            f"{source_name}: missing item slot {slot + 1} for {side} row {row + 1}"
                        )
                    if normalize_label(raw) == "empty":
                        items.append(
                            {"team": side, "row": row, "slot": slot, "occupancy": "empty"}
                        )
                        semantic_items.append(None)
                        continue
                    item_id, item_name = lookup(
                        raw,
                        item_index,
                        kind="item",
                        source=f"{source_name}:{side}:{row + 1}:slot:{slot + 1}",
                    )
                    items.append(
                        {
                            "team": side,
                            "row": row,
                            "slot": slot,
                            "occupancy": "occupied",
                            "stable_id": item_id,
                            "legacy_name": item_name,
                        }
                    )
                    semantic_items.append(item_name)
                semantic_player["items"] = semantic_items
            semantic_teams[side].append(semantic_player)

    rows = [
        {"team": side, "row": row, "y_start": top, "y_end": top + ROW_HEIGHT}
        for side in ("ally", "enemy")
        for row, top in enumerate(ROW_TOPS)
    ]
    return {
        "annotation_version": "1.0",
        "screen_type": schema_screen,
        "geometry": {"viewport": VIEWPORT, "rows": rows},
        "heroes": heroes,
        "items": items,
        "fields": fields,
        "semantic_json": {
            "screen_type": semantic_screen,
            "match": {
                key: scalar(FIELD_ALIASES.get(key, key), value)
                for key, value in parsed.match.items()
                if key not in SKIP_KEYS
            },
            "teams": semantic_teams,
        },
    }


def compile_manifest(
    dataset_root: Path,
    catalog_path: Path,
    reviewed_at: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    source_dir = dataset_root / "sources"
    hero_index, item_index = catalog_index(catalog_path)
    samples: list[dict[str, Any]] = []
    freeze_files: list[dict[str, Any]] = []

    for stem, (semantic_screen, schema_screen) in SCREEN_FILES.items():
        image_path = source_dir / f"{stem}.jpeg"
        truth_path = source_dir / f"{stem}.txt"
        parsed = parse_truth(truth_path)
        with Image.open(image_path) as image:
            width, height = image.size
        if (width, height) != (1600, 1199):
            raise ValueError(f"{image_path}: expected 1600x1199, got {width}x{height}")
        annotation = build_annotation(
            parsed,
            semantic_screen,
            schema_screen,
            hero_index,
            item_index,
            source_name=truth_path.name,
        )
        samples.append(
            {
                "sample_id": stem,
                "match_group_id": MATCH_GROUP_ID,
                "image_path": f"sources/{image_path.name}",
                "sha256": sha256_file(image_path),
                "approval": "approved",
                "reviewer": "user-confirmed-manual-truth",
                "reviewed_at": reviewed_at.isoformat(),
                "source": {
                    "width": width,
                    "height": height,
                    "device_source": "private-user-capture",
                    "ui_profile": "starter-2026.07-standard",
                    "patch": "2026.07",
                    "compression": "jpeg",
                    "capture_session": MATCH_GROUP_ID,
                },
                "annotation": annotation,
                "slices": {
                    "semantic_screen_type": semantic_screen,
                    "privacy": "private",
                    "leakage_group": MATCH_GROUP_ID,
                },
            }
        )
        for path in (image_path, truth_path):
            freeze_files.append(
                {
                    "path": f"sources/{path.name}",
                    "sha256": sha256_file(path),
                    "bytes": path.stat().st_size,
                    "mode": oct(path.stat().st_mode & 0o777),
                }
            )

    manifest = {
        "dataset_version": "starter-private-v1",
        "annotation_version": "1.0",
        "created_at": reviewed_at.isoformat(),
        "samples": samples,
    }
    AnnotationManifest.model_validate(manifest)
    freeze_manifest = {
        "freeze_version": "1.0",
        "frozen_at": reviewed_at.isoformat(),
        "source": "five user-corrected TXT/JPEG pairs",
        "approval_evidence": "user confirmed all TXT files were manually edited before calibration",
        "privacy": "private; ignored by Git",
        "catalog_version": json.loads(catalog_path.read_text(encoding="utf-8"))["catalog_version"],
        "match_group_id": MATCH_GROUP_ID,
        "files": sorted(freeze_files, key=lambda item: item["path"]),
    }
    return manifest, freeze_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--reviewed-at", required=True)
    arguments = parser.parse_args()
    reviewed_at = datetime.fromisoformat(arguments.reviewed_at)
    if reviewed_at.tzinfo is None:
        parser.error("--reviewed-at must include an explicit timezone")
    manifest, freeze_manifest = compile_manifest(
        arguments.dataset_root,
        arguments.catalog,
        reviewed_at,
    )
    (arguments.dataset_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (arguments.dataset_root / "freeze_manifest.json").write_text(
        json.dumps(freeze_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "dataset_root": str(arguments.dataset_root),
                "samples": len(manifest["samples"]),
                "frozen_files": len(freeze_manifest["files"]),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
