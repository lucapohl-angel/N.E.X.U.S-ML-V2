#!/usr/bin/env python3
"""Build privacy-safe profile fixtures from the ignored private starter captures.

Only fixed UI controls, tab icons, and decorative panel edges are exported. Player rows,
names, portraits, statistics, timestamps, and battle IDs are never included in an asset.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / "data/private/starter_screenshots"
PROFILE_ROOT = ROOT / "profiles"
VIEWPORT = (0, 150, 1600, 1050)


def box(x1, y1, x2, y2):
    return [float(x1), float(y1), float(x2), float(y2)]


def field(
    field_id,
    kind,
    screens,
    bounds,
    *,
    side=None,
    parser=None,
    row=True,
    slot=False,
    slot_step=0.0,
    mask="rectangle",
    context=4.0,
):
    return {
        "field_id": field_id,
        "kind": kind,
        "scope": "viewport" if side is None else "row",
        "screen_types": screens,
        "canonical_box": bounds,
        "side": side,
        "row_repeat": row if side is not None else False,
        "row_step": 116.0 if side is not None and row else 0.0,
        "slot_repeat": slot,
        "slot_step": slot_step,
        "parser": parser,
        "tight_padding": 0.0,
        "context_padding": context,
        "mask_shape": mask,
        "dynamic": True,
    }


def semantic_fields():
    all_screens = ["hero_item_build", "overall", "dps", "farm", "team"]
    stats_screens = ["overall", "dps", "farm", "team"]
    result = [
        field(
            "battle_id",
            "metadata",
            all_screens,
            box(90, 872, 300, 900),
            parser="battle_id_18",
            side=None,
            row=False,
            context=2.0,
        ),
        field(
            "result",
            "metadata",
            all_screens,
            box(590, 30, 1010, 118),
            parser="result",
            side=None,
            row=False,
            context=3.0,
        ),
        field(
            "team_kills",
            "metadata",
            all_screens,
            box(440, 40, 565, 115),
            parser="small_integer",
            side=None,
            row=False,
            context=3.0,
        ),
        field(
            "enemy_kills",
            "metadata",
            all_screens,
            box(1035, 40, 1165, 115),
            parser="small_integer",
            side=None,
            row=False,
            context=3.0,
        ),
        field(
            "duration",
            "metadata",
            all_screens,
            box(1170, 98, 1365, 139),
            parser="duration",
            side=None,
            row=False,
            context=2.0,
        ),

        field(
            "hero_portrait",
            "hero",
            all_screens,
            box(132, 190, 260, 299),
            side="ally",
            mask="ellipse",
            context=7.0,
        ),
        field(
            "hero_portrait",
            "hero",
            all_screens,
            box(1338, 190, 1463, 299),
            side="enemy",
            mask="ellipse",
            context=7.0,
        ),
        field(
            "player_name",
            "ocr",
            all_screens,
            box(279, 195, 490, 226),
            side="ally",
            parser="player_name",
        ),
        field(
            "player_name",
            "ocr",
            all_screens,
            box(1102, 195, 1328, 226),
            side="enemy",
            parser="player_name",
        ),
        field(
            "level",
            "ocr",
            all_screens,
            box(162, 260, 205, 293),
            side="ally",
            parser="level",
        ),
        field(
            "level",
            "ocr",
            all_screens,
            box(1382, 260, 1428, 293),
            side="enemy",
            parser="level",
        ),
    ]
    hero_item = ["hero_item_build"]
    for side, starts, widths in (
        ("ally", (497, 535, 574, 612), (30, 30, 34, 75)),
        # Enemy table ordering is gold, K, D, A in screen coordinates; keep semantic order here.
        ("enemy", (1005, 1044, 1083, 918), (30, 30, 19, 75)),
    ):
        names = ("kills", "deaths", "assists", "total_gold")
        for name, start, width in zip(names, starts, widths, strict=True):
            result.append(
                field(
                    name,
                    "ocr",
                    hero_item,
                    box(start, 194, start + width, 226),
                    side=side,
                    parser="large_integer" if name == "total_gold" else "short_integer",
                )
            )
    result.extend(
        [
            field(
                "rating",
                "ocr",
                hero_item,
                box(700, 257, 760, 294),
                side="ally",
                parser="decimal",
            ),
            field(
                "rating",
                "ocr",
                hero_item,
                box(840, 257, 900, 294),
                side="enemy",
                parser="decimal",
            ),
            field(
                "item",
                "item",
                hero_item,
                box(280, 234, 337, 291),
                side="ally",
                slot=True,
                slot_step=58.2,
                mask="ellipse",
                context=3.0,
            ),
            field(
                "item",
                "item",
                hero_item,
                box(979, 234, 1036, 291),
                side="enemy",
                slot=True,
                slot_step=58.2,
                mask="ellipse",
                context=3.0,
            ),
        ]
    )

    columns = {
        "overall": (
            ("hero_damage", 280, 390, "large_integer", 226, 255),
            ("hero_damage_percent", 280, 390, "percentage", 255, 292),
            ("turret_damage", 404, 520, "large_integer", 226, 255),
            ("turret_damage_percent", 404, 520, "percentage", 255, 292),
            ("damage_taken", 531, 650, "large_integer", 226, 255),
            ("damage_taken_percent", 531, 650, "percentage", 255, 292),
            ("teamfight_participation", 659, 774, "percentage", 255, 292),
        ),
        "dps": (
            ("hero_damage", 280, 455, "large_integer", 226, 263),
            ("hero_damage_percent", 465, 523, "percentage", 255, 292),
            ("consecutive_kills", 530, 720, "small_integer", 226, 263),
        ),
        "farm": (
            ("total_gold", 280, 390, "large_integer", 226, 255),
            ("total_gold_percent", 280, 390, "percentage", 255, 292),
            ("jungle_gold", 405, 520, "large_integer", 226, 255),
            ("jungle_gold_percent", 405, 520, "percentage", 255, 292),
            ("kill_gold", 531, 650, "large_integer", 226, 255),
            ("kill_gold_percent", 531, 650, "percentage", 255, 292),
            ("minion_gold", 659, 774, "large_integer", 226, 255),
            ("minion_gold_percent", 659, 774, "percentage", 255, 292),
        ),
        "team": (
            ("teamfight_participation", 280, 390, "percentage", 255, 292),
            ("crowd_control", 405, 520, "large_integer", 226, 255),
            ("crowd_control_percent", 405, 520, "percentage", 255, 292),
            ("healing_and_shields", 531, 650, "large_integer", 226, 255),
            ("healing_and_shields_percent", 531, 650, "percentage", 255, 292),
            ("damage_taken", 659, 774, "large_integer", 226, 255),
            ("damage_taken_percent", 659, 774, "percentage", 255, 292),
        ),
    }
    for screen, definitions in columns.items():
        for side, offset in (("ally", 0), ("enemy", 554)):
            for name, left, right, parser, top, bottom in definitions:
                # Enemy columns start independently rather than being mirrored from ally boxes.
                enemy_left = left + offset
                enemy_right = right + offset
                result.append(
                    field(
                        name,
                        "ocr",
                        [screen],
                        box(enemy_left, top, enemy_right, bottom),
                        side=side,
                        parser=parser,
                    )
                )
    assert stats_screens == list(columns)
    return result


def save_crop(image, viewport_box, crop_box, target):
    vx1, vy1, _, _ = viewport_box
    x1, y1, x2, y2 = crop_box
    crop = image.crop((vx1 + x1, vy1 + y1, vx1 + x2, vy1 + y2))
    target.parent.mkdir(parents=True, exist_ok=True)
    crop.save(target, format="PNG", optimize=True)


def write_mask(size, target, border_only=False):
    width, height = size
    mask = np.full((height, width), 255, dtype=np.uint8)
    if border_only:
        mask[:, :] = 0
        border = max(4, min(width, height) // 8)
        mask[:border, :] = 255
        mask[-border:, :] = 255
        mask[:, :border] = 255
        mask[:, -border:] = 255
    Image.fromarray(mask, mode="L").save(target, format="PNG", optimize=True)


def starter_profile():
    output = PROFILE_ROOT / "starter-2026.07-standard"
    assets = output / "assets"
    sources = {
        "hero_item_build": PRIVATE / "hero_item_screen.jpeg",
        "overall": PRIVATE / "overall_screen.jpeg",
        "dps": PRIVATE / "dps_screen.jpeg",
        "farm": PRIVATE / "farm_screen.jpeg",
        "team": PRIVATE / "team_screen.jpeg",
    }
    images = {}
    for screen, path in sources.items():
        image = Image.open(path).convert("RGB")
        if image.size != (1600, 1199):
            raise RuntimeError(f"unexpected starter dimensions for {path}: {image.size}")
        images[screen] = image

    common_anchors = [
        ("play_control", "control", (0, 8, 78, 82), (0, 0, 105, 105), False),
        ("top_crest", "header", (735, 0, 865, 48), (690, 0, 910, 80), False),
        ("center_header_split", "panel", (774, 136, 826, 190), (735, 115, 865, 225), False),
        ("data_button_frame", "footer", (12, 795, 254, 866), (0, 760, 300, 900), True),
        ("quit_button_frame", "footer", (1345, 795, 1590, 866), (1300, 760, 1600, 900), True),
    ]
    anchor_payload = []
    for anchor_id, family, bounds, search, border_only in common_anchors:
        template = assets / f"anchor_{anchor_id}.png"
        mask = assets / f"anchor_{anchor_id}_mask.png"
        save_crop(images["hero_item_build"], VIEWPORT, bounds, template)
        write_mask((bounds[2] - bounds[0], bounds[3] - bounds[1]), mask, border_only)
        anchor_payload.append(
            {
                "anchor_id": anchor_id,
                "stable_version": "starter-anchor-v1",
                "family": family,
                "canonical_box": box(*bounds),
                "search_box": box(*search),
                "template_path": f"assets/{template.name}",
                "mask_path": f"assets/{mask.name}",
                "screen_types": [],
                "minimum_score": 0.58 if border_only else 0.72,
                "minimum_margin": 0.015,
            }
        )

    evidence_boxes = {
        "hero_item_build": (468, 135, 690, 187, "header"),
        "overall": (388, 786, 511, 898, "tab"),
        "dps": (520, 786, 643, 898, "tab"),
        "team": (655, 786, 790, 898, "tab"),
        "farm": (842, 786, 980, 898, "tab"),
    }
    evidence = []
    for screen, (x1, y1, x2, y2, kind) in evidence_boxes.items():
        template = assets / f"screen_{screen}.png"
        mask = assets / f"screen_{screen}_mask.png"
        save_crop(images[screen], VIEWPORT, (x1, y1, x2, y2), template)
        write_mask((x2 - x1, y2 - y1), mask)
        evidence.append(
            {
                "evidence_id": f"selected_{screen}",
                "screen_type": screen,
                "kind": kind,
                "canonical_box": box(x1, y1, x2, y2),
                "template_path": f"assets/{template.name}",
                "mask_path": f"assets/{mask.name}",
                "weight": 0.9 if kind == "tab" else 0.8,
            }
        )

    profile = {
        "schema_version": "2.0",
        "profile_id": "starter-2026.07-standard",
        "profile_version": "1.3.0",
        "verification": "verified",
        "verification_evidence": [
            "five private same-match screen types visually inspected",
            "native 1600x900 viewport verified inside each 1600x1199 capture",
            "committed assets contain only fixed controls tabs and decorative UI",
        ],
        "runtime_enabled": True,
        "canonical_size": {"width": 1600, "height": 900},
        "screen_types": ["hero_item_build", "overall", "dps", "farm", "team"],
        "compatibility": {
            "ui_family": "mlbb-postmatch-2026.07-standard",
            "patch_min": "2026.07",
            "patch_max": None,
            "languages": ["en"],
            "allowed_aspect_error": 0.045,
            "allows_cropped_edges": True,
            "requires_second_device_verification": True,
            "notes": ["one physical capture geometry only; unseen resolutions are synthetic"],
        },
        "panels": [
            {
                "side": "ally",
                "canonical_box": box(0, 185, 800, 766),
                "edge_search_radius": 20.0,
                "independent_registration": True,
            },
            {
                "side": "enemy",
                "canonical_box": box(800, 185, 1600, 766),
                "edge_search_radius": 20.0,
                "independent_registration": True,
            },
        ],
        "row_relation": {
            "count": 5,
            "first_top": 185.0,
            "height": 116.0,
            "step": 116.0,
            "search_radius": 18.0,
            "spacing_tolerance": 0.12,
        },
        "slot_relation": {
            "count": 6,
            "centers": {
                "ally": [308.5, 366.5, 424.5, 482.5, 540.5, 598.5],
                "enemy": [1007.5, 1065.5, 1123.5, 1181.5, 1239.5, 1297.5],
            },
            "center_y_in_row": 77.0,
            "diameter": 55.0,
            "search_radius": 8.0,
        },
        "anchors": anchor_payload,
        "screen_evidence": evidence,
        "dynamic_masks": [
            {
                "mask_id": "team_scores",
                "region": box(420, 35, 1180, 138),
                "reason": "result and scores vary",
            },
            {
                "mask_id": "player_table",
                "region": box(120, 185, 1480, 766),
                "reason": "names portraits stats items and badges vary",
            },
            {
                "mask_id": "match_metadata",
                "region": box(0, 866, 650, 900),
                "reason": "battle ID is identifying",
            },
            {
                "mask_id": "timestamp",
                "region": box(1160, 90, 1600, 138),
                "reason": "capture metadata varies",
            },
        ],
        "fields": semantic_fields(),
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "profile.json").write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    for image in images.values():
        image.close()
    return profile


def scale_box(values, factor):
    return [round(value * factor, 4) for value in values]


def legacy_profile(starter):
    profile = json.loads(json.dumps(starter))
    factor = 1.2
    profile["profile_id"] = "legacy-1920x1080-bootstrap"
    profile["profile_version"] = "0.1.0-bootstrap"
    profile["verification"] = "bootstrap_unverified"
    profile["verification_evidence"] = [
        "seeded from legacy percentage coordinate maps",
        "no second-device screenshot was supplied for visual verification",
    ]
    profile["runtime_enabled"] = False
    profile["canonical_size"] = {"width": 1920, "height": 1080}
    profile["compatibility"]["ui_family"] = "legacy-v1-coordinate-seed"
    profile["compatibility"]["requires_second_device_verification"] = True
    profile["compatibility"]["notes"] = [
        "bootstrap metadata only; cannot accept runtime geometry",
        "must be replaced or verified from an independent device capture",
    ]
    profile["anchors"] = []
    profile["screen_evidence"] = []
    for panel in profile["panels"]:
        panel["canonical_box"] = scale_box(panel["canonical_box"], factor)
        panel["edge_search_radius"] *= factor
    relation = profile["row_relation"]
    for key in ("first_top", "height", "step", "search_radius"):
        relation[key] *= factor
    slots = profile["slot_relation"]
    slots["centers"] = {
        side: [round(value * factor, 4) for value in values]
        for side, values in slots["centers"].items()
    }
    for key in ("center_y_in_row", "diameter", "search_radius"):
        slots[key] *= factor
    for dynamic_mask in profile["dynamic_masks"]:
        dynamic_mask["region"] = scale_box(dynamic_mask["region"], factor)
    for definition in profile["fields"]:
        definition["canonical_box"] = scale_box(definition["canonical_box"], factor)
        definition["row_step"] *= factor
        definition["slot_step"] *= factor
        definition["tight_padding"] *= factor
        definition["context_padding"] *= factor
    output = PROFILE_ROOT / profile["profile_id"]
    output.mkdir(parents=True, exist_ok=True)
    (output / "profile.json").write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")


def main():
    starter = starter_profile()
    legacy_profile(starter)
    print("generated verified privacy-safe starter profile and unverified legacy bootstrap profile")


if __name__ == "__main__":
    main()
