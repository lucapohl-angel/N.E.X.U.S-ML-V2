from __future__ import annotations

import io
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest
from PIL import Image

from nexus_v2.input import (
    DecodeLimits,
    ImageDecoder,
    ImageInputError,
    analyze_quality,
    detect_viewports,
)
from nexus_v2.layout import (
    ProfileRegistry,
    ScreenType,
    build_semantic_crops,
    solve_geometry,
)
from nexus_v2.layout.profiles import (
    FieldKind,
    ProfileVerification,
    SemanticFieldDefinition,
    TeamSide,
)
from nexus_v2.schemas.result import ExtractionStatus

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / "data/private/starter_screenshots"
CURRENT_DEVICE_DATASET = ROOT / "data/private/review_dataset/family-01-current-device"
SECOND_DEVICE_DATASET = ROOT / "data/private/review_dataset/family-02-ipad-2388x1668"
HERO_CATALOG_BATCH = ROOT / "data/private/review_dataset/family-01-hero-catalog-2026-08-02/batch-01"
EXPECTED_SCREENS = {
    "hero_item_screen": ScreenType.HERO_ITEM_BUILD,
    "overall_screen": ScreenType.OVERALL,
    "dps_screen": ScreenType.DPS,
    "farm_screen": ScreenType.FARM,
    "team_screen": ScreenType.TEAM,
}


def _png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _assert_no_ocr_crop_overlaps(crops: list[Any]) -> None:
    ocr_crops = [crop for crop in crops if crop.kind in {FieldKind.OCR, FieldKind.METADATA}]
    for index, left in enumerate(ocr_crops):
        ax1, ay1, ax2, ay2 = left.tight_box
        for right in ocr_crops[index + 1 :]:
            bx1, by1, bx2, by2 = right.tight_box
            overlap_width = max(0, min(ax2, bx2) - max(ax1, bx1))
            overlap_height = max(0, min(ay2, by2) - max(ay1, by1))
            assert overlap_width * overlap_height == 0, (
                left.field_id,
                right.field_id,
                left.tight_box,
                right.tight_box,
            )


def test_decoder_preserves_native_pixels_across_supported_inputs(tmp_path: Path) -> None:
    rgb = np.zeros((11, 17, 3), dtype=np.uint8)
    rgb[:, :, 0] = 12
    rgb[:, :, 1] = 34
    rgb[:, :, 2] = 56
    pil = Image.fromarray(rgb)
    encoded = _png_bytes(pil)
    path = tmp_path / "source.png"
    path.write_bytes(encoded)
    decoder = ImageDecoder(DecodeLimits(numpy_color_order="rgb"))

    decoded_path = decoder.decode(path)
    decoded_bytes = decoder.decode(encoded)
    decoded_pil = decoder.decode(pil)
    decoded_array = decoder.decode(rgb)

    for decoded in (decoded_path, decoded_bytes, decoded_pil, decoded_array):
        assert (decoded.width, decoded.height) == (17, 11)
        assert np.array_equal(decoded.rgb, rgb)
        assert not decoded.rgb.flags.writeable


def test_decoder_rejects_corrupt_or_oversized_inputs() -> None:
    decoder = ImageDecoder()
    with pytest.raises(ImageInputError):
        decoder.decode(b"not an image")
    with pytest.raises(ImageInputError):
        decoder.decode(cast(Any, np.zeros((4, 4), dtype=np.float32)))


def test_quality_routes_structureless_image_to_low_quality() -> None:
    image = ImageDecoder().decode(np.zeros((320, 640, 3), dtype=np.uint8))
    quality = analyze_quality(image)
    assert quality.status is ExtractionStatus.LOW_QUALITY
    assert quality.screenshot_validity_score < 0.28
    assert "insufficient_dynamic_range" in quality.reasons


def test_viewport_candidates_are_ranked_deterministically() -> None:
    canvas = np.zeros((700, 960, 3), dtype=np.uint8)
    rng = np.random.default_rng(7)
    canvas[80:620] = rng.integers(30, 220, size=(540, 960, 3), dtype=np.uint8)
    image = ImageDecoder().decode(canvas)
    first = detect_viewports(image, max_candidates=6)
    second = detect_viewports(image, max_candidates=6)
    assert first == second
    assert first
    assert first[0].box in {(0, 79, 960, 619), (0, 80, 960, 620)}


def test_profile_registry_enables_only_human_verified_profile() -> None:
    registry = ProfileRegistry.load(ROOT / "profiles")
    starter = registry.get("starter-2026.07-standard")
    legacy = registry.get("legacy-1920x1080-bootstrap")
    assert starter.profile.verification is ProfileVerification.VERIFIED
    assert starter in registry.runtime_profiles
    assert legacy.profile.verification is ProfileVerification.BOOTSTRAP_UNVERIFIED
    assert legacy not in registry.runtime_profiles


def test_starter_profile_uses_semantic_battle_id_and_level_constraints() -> None:
    profile = ProfileRegistry.load(ROOT / "profiles").get("starter-2026.07-standard").profile
    battle_id = [field for field in profile.fields if field.field_id == "battle_id"]
    levels = [field for field in profile.fields if field.field_id == "level"]

    assert len(battle_id) == 1
    assert battle_id[0].parser == "battle_id_18"
    assert battle_id[0].canonical_box[0] == 90.0
    assert len(levels) == 2
    assert {field.parser for field in levels} == {"level"}

    invalid = battle_id[0].model_dump(mode="json")
    invalid["parser"] = "typo_falls_through_to_text"
    with pytest.raises(ValueError, match="supported semantic parser"):
        SemanticFieldDefinition.model_validate(invalid)


def test_profiles_do_not_emit_removed_played_at_field() -> None:
    registry = ProfileRegistry.load(ROOT / "profiles")
    for loaded in registry.profiles:
        assert all(field.field_id != "played_at" for field in loaded.profile.fields)


@pytest.mark.integration
def test_private_starter_geometry_and_native_crops() -> None:
    missing = [stem for stem in EXPECTED_SCREENS if not (PRIVATE / f"{stem}.jpeg").is_file()]
    if missing:
        pytest.skip("private starter screenshots are unavailable")
    registry = ProfileRegistry.load(ROOT / "profiles")
    loaded = registry.get("starter-2026.07-standard")
    decoder = ImageDecoder()

    for stem, expected in EXPECTED_SCREENS.items():
        image = decoder.decode(PRIVATE / f"{stem}.jpeg")
        geometry = solve_geometry(image, registry)
        repeated = solve_geometry(image, registry)
        assert geometry == repeated
        assert geometry.status is ExtractionStatus.OK
        assert geometry.screen.screen_type is expected
        assert geometry.viewport is not None
        assert geometry.viewport.box in {(0, 149, 1600, 1049), (0, 150, 1600, 1050)}
        assert {panel.side for panel in geometry.panels} == set(TeamSide)
        assert all(panel.independently_solved for panel in geometry.panels)

        crops = build_semantic_crops(image, loaded, geometry)
        assert crops
        assert not any(crop.clipped for crop in crops)
        assert all(
            crop.tight_rgb.shape[1] == crop.tight_box[2] - crop.tight_box[0] for crop in crops
        )
        assert all(
            crop.tight_rgb.shape[0] == crop.tight_box[3] - crop.tight_box[1] for crop in crops
        )
        _assert_no_ocr_crop_overlaps(list(crops))
        heroes = [crop for crop in crops if crop.kind is FieldKind.HERO]
        assert len(heroes) == 10
        if expected is ScreenType.HERO_ITEM_BUILD:
            items = [crop for crop in crops if crop.kind is FieldKind.ITEM]
            assert len(items) == 60


@pytest.mark.integration
def test_private_current_device_screen_variants() -> None:
    games = [CURRENT_DEVICE_DATASET / f"game-{game_number:02d}" for game_number in range(2, 6)]
    if any(not (game / f"{stem}.jpeg").is_file() for game in games for stem in EXPECTED_SCREENS):
        pytest.skip("private current-device review screenshots are unavailable")

    registry = ProfileRegistry.load(ROOT / "profiles")
    decoder = ImageDecoder()
    for game in games:
        for stem, expected in EXPECTED_SCREENS.items():
            image = decoder.decode(game / f"{stem}.jpeg")
            geometry = solve_geometry(image, registry)
            assert geometry.status is ExtractionStatus.OK
            assert geometry.screen.screen_type is expected
            assert geometry.profile_id is not None
            crops = build_semantic_crops(image, registry.get(geometry.profile_id), geometry)
            _assert_no_ocr_crop_overlaps(list(crops))


@pytest.mark.integration
def test_private_second_device_geometry_and_native_crops() -> None:
    games = [SECOND_DEVICE_DATASET / f"game-{game_number:02d}" for game_number in range(1, 3)]
    if any(not (game / f"{stem}.png").is_file() for game in games for stem in EXPECTED_SCREENS):
        pytest.skip("private second-device review screenshots are unavailable")

    registry = ProfileRegistry.load(ROOT / "profiles")
    decoder = ImageDecoder()
    for game in games:
        for stem, expected in EXPECTED_SCREENS.items():
            image = decoder.decode(game / f"{stem}.png")
            geometry = solve_geometry(image, registry)
            assert geometry.status is ExtractionStatus.OK
            assert geometry.screen.screen_type is expected
            assert geometry.viewport is not None
            assert geometry.viewport.box == (0, 161, 2388, 1504)
            assert all(panel.independently_solved for panel in geometry.panels)
            assert geometry.profile_id is not None
            crops = build_semantic_crops(image, registry.get(geometry.profile_id), geometry)
            assert not any(crop.clipped for crop in crops)
            assert sum(crop.kind is FieldKind.HERO for crop in crops) == 10
            if expected is ScreenType.HERO_ITEM_BUILD:
                assert sum(crop.kind is FieldKind.ITEM for crop in crops) == 60
            _assert_no_ocr_crop_overlaps(list(crops))


@pytest.mark.integration
def test_private_floryn_rows_expand_to_seven_items_only_with_extra_icon_evidence() -> None:
    screenshots = sorted(HERO_CATALOG_BATCH.glob("hero_item_*.png"))
    if len(screenshots) != 30:
        pytest.skip("private reviewed hero catalog batch is unavailable")

    expected_seven = {
        ("hero_item_0011_IMG_4129.png", "ally", 4),
        ("hero_item_0012_IMG_4130.png", "enemy", 1),
        ("hero_item_0014_IMG_4132.png", "ally", 4),
        ("hero_item_0020_IMG_4138.png", "ally", 3),
        ("hero_item_0029_IMG_4147.png", "enemy", 2),
        ("hero_item_0030_IMG_4148.png", "ally", 2),
    }
    observed_seven: set[tuple[str, str, int]] = set()
    registry = ProfileRegistry.load(ROOT / "profiles")
    decoder = ImageDecoder()
    for screenshot in screenshots:
        image = decoder.decode(screenshot)
        geometry = solve_geometry(image, registry)
        assert geometry.profile_id is not None
        crops = build_semantic_crops(image, registry.get(geometry.profile_id), geometry)
        for side in TeamSide:
            for row in range(5):
                items = [
                    crop
                    for crop in crops
                    if crop.kind is FieldKind.ITEM and crop.side is side and crop.row == row
                ]
                assert len(items) in {6, 7}
                assert [crop.slot for crop in items] == list(range(len(items)))
                if len(items) == 7:
                    observed_seven.add((screenshot.name, side.value, row))

    assert observed_seven == expected_seven
