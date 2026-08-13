from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np
import pytest
from numpy.typing import NDArray

from nexus_v2.engine import NexusV2Engine
from nexus_v2.layout.cropper import SemanticCrop
from nexus_v2.layout.profiles import FieldKind, ScreenType, TeamSide
from nexus_v2.recognition import (
    HeroAcceptancePolicy,
    HeroBalancedPolicy,
    HeroRerankerPolicy,
    ReferenceLibrary,
    VisualMatcher,
    VisualMatcherConfig,
    VisualReference,
    resolve_hero_recognition,
    resolve_item_recognition,
)
from nexus_v2.schemas.result import ExtractionStatus

ROOT = Path(__file__).resolve().parents[1]


def _pattern(color: tuple[int, int, int], diagonal: bool) -> NDArray[np.uint8]:
    image = np.zeros((64, 64, 3), dtype=np.uint8)
    cv2.circle(image, (32, 32), 27, color, thickness=-1)
    if diagonal:
        cv2.line(image, (15, 48), (48, 15), (255, 255, 255), thickness=7)
    else:
        cv2.rectangle(image, (25, 14), (39, 50), (255, 255, 255), thickness=-1)
    return image


def _write_rgb(path: Path, image: NDArray[np.uint8]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    assert cv2.imwrite(str(path), cv2.cvtColor(image, cv2.COLOR_RGB2BGR))


def _catalog(tmp_path: Path) -> tuple[Path, NDArray[np.uint8], NDArray[np.uint8]]:
    first = _pattern((230, 30, 30), True)
    second = _pattern((30, 60, 230), False)
    _write_rgb(tmp_path / "assets/heroes/a/a.png", first)
    _write_rgb(tmp_path / "assets/heroes/b/b.png", second)
    _write_rgb(tmp_path / "assets/items/a/a.png", first)
    _write_rgb(tmp_path / "assets/items/b/b.png", second)
    payload = {
        "catalog_version": "test-v1",
        "heroes": [
            {
                "id": "hero_a",
                "canonical_name": "Hero A",
                "visual_versions": [{"id": "hero_a_visual", "asset_path": "assets/heroes/a/a.png"}],
            },
            {
                "id": "hero_b",
                "canonical_name": "Hero B",
                "visual_versions": [{"id": "hero_b_visual", "asset_path": "assets/heroes/b/b.png"}],
            },
        ],
        "items": [
            {
                "id": "item_a",
                "canonical_name": "Item A",
                "classification_enabled": True,
                "visual_versions": [{"id": "item_a_visual", "asset_path": "assets/items/a/a.png"}],
            },
            {
                "id": "item_b",
                "canonical_name": "Item B",
                "classification_enabled": True,
                "visual_versions": [{"id": "item_b_visual", "asset_path": "assets/items/b/b.png"}],
            },
        ],
    }
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path, first, second


def _crop(
    image: NDArray[np.uint8],
    *,
    kind: FieldKind,
    slot: int | None = None,
    side: TeamSide = TeamSide.ALLY,
) -> SemanticCrop:
    return SemanticCrop(
        field_id=kind.value,
        kind=kind,
        screen_type=ScreenType.HERO_ITEM_BUILD,
        side=side,
        row=0,
        slot=slot,
        parser=None,
        tight_box=(0, 0, 64, 64),
        context_box=(0, 0, 64, 64),
        tight_rgb=image,
        context_rgb=image,
        mask=None,
        clipped=False,
    )


def test_visual_matcher_returns_stable_hero_id_and_raw_similarity(tmp_path: Path) -> None:
    catalog, first, _ = _catalog(tmp_path)
    library = ReferenceLibrary.load(catalog, kind="hero")
    matcher = VisualMatcher(library, VisualMatcherConfig(minimum_score=0.6, minimum_margin=0.01))
    result = matcher.match_hero(_crop(first, kind=FieldKind.HERO))
    assert result.status is ExtractionStatus.OK
    assert result.hero_id == "hero_a"
    assert result.candidates[0].candidate_id == "hero_a"
    assert "fused_similarity" in result.candidates[0].scores


def test_hero_preprocessing_is_opt_in_and_preserves_original_score_floor(tmp_path: Path) -> None:
    catalog, first, _ = _catalog(tmp_path)
    library = ReferenceLibrary.load(catalog, kind="hero")
    crop = _crop(
        np.asarray(np.clip(first.astype(np.int16) - 35, 0, 255), dtype=np.uint8),
        kind=FieldKind.HERO,
    )
    baseline = VisualMatcher(
        library, VisualMatcherConfig(minimum_score=0.0, minimum_margin=0.0)
    ).match_hero(crop)
    enhanced = VisualMatcher(
        library,
        VisualMatcherConfig(
            minimum_score=0.0,
            minimum_margin=0.0,
            hero_preprocessing_views=("clahe_luma", "gamma_085", "gamma_115", "unsharp"),
            preprocessing_bonus_weight=0.5,
        ),
    ).match_hero(crop)

    assert baseline.hero_id == "hero_a"
    assert enhanced.hero_id == baseline.hero_id
    assert enhanced.confidence is not None
    assert baseline.confidence is not None
    assert enhanced.confidence >= baseline.confidence
    assert enhanced.candidates[0].scores["original_similarity"] == pytest.approx(
        baseline.confidence
    )
    assert enhanced.candidates[0].scores["preprocessing_gain"] >= 0.0


def test_invalid_hero_preprocessing_configuration_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported hero preprocessing"):
        VisualMatcherConfig(hero_preprocessing_views=("aggressive_magic",))
    with pytest.raises(ValueError, match="bonus weight"):
        VisualMatcherConfig(preprocessing_bonus_weight=1.1)
    with pytest.raises(ValueError, match="top-n"):
        VisualMatcherConfig(preprocessing_rerank_top_n=0)
    with pytest.raises(ValueError, match="preprocessing sides"):
        VisualMatcherConfig(hero_preprocessing_sides=("spectator",))
    with pytest.raises(ValueError, match="must be unique"):
        VisualMatcherConfig(hero_preprocessing_sides=("ally", "ally"))
    with pytest.raises(ValueError, match="scoring backend"):
        VisualMatcherConfig(hero_scoring_backend="approximate")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="vectorized chunk size"):
        VisualMatcherConfig(vectorized_chunk_size=0)
    with pytest.raises(ValueError, match="scalar refinement"):
        VisualMatcherConfig(top_k=5, vectorized_scalar_refine_top_n=4)


def _assert_scalar_vectorized_parity(
    scalar: VisualMatcher,
    vectorized: VisualMatcher,
    crop: SemanticCrop,
) -> None:
    scalar_result = scalar.match_hero(crop)
    vectorized_result = vectorized.match_hero(crop)
    assert vectorized_result.status is scalar_result.status
    assert vectorized_result.hero_id == scalar_result.hero_id
    assert [candidate.candidate_id for candidate in vectorized_result.candidates] == [
        candidate.candidate_id for candidate in scalar_result.candidates
    ]
    for scalar_candidate, vectorized_candidate in zip(
        scalar_result.candidates, vectorized_result.candidates, strict=True
    ):
        assert vectorized_candidate.scores.keys() == scalar_candidate.scores.keys()
        for key, scalar_score in scalar_candidate.scores.items():
            assert vectorized_candidate.scores[key] == pytest.approx(scalar_score, abs=1e-5)


def test_vectorized_hero_scoring_matches_scalar_scores_and_is_deterministic(
    tmp_path: Path,
) -> None:
    catalog, first, _ = _catalog(tmp_path)
    library = ReferenceLibrary.load(catalog, kind="hero")
    config = VisualMatcherConfig(minimum_score=0.0, minimum_margin=0.0)
    scalar = VisualMatcher(library, config)
    vectorized = VisualMatcher(
        library,
        replace(config, hero_scoring_backend="vectorized", vectorized_chunk_size=1),
    )
    crop = _crop(first, kind=FieldKind.HERO)

    _assert_scalar_vectorized_parity(scalar, vectorized, crop)
    first_result = vectorized.match_hero(crop)
    second_result = vectorized.match_hero(crop)
    assert first_result == second_result


def test_vectorized_prepared_alignments_share_the_single_feature_bank(tmp_path: Path) -> None:
    catalog, _, _ = _catalog(tmp_path)
    matcher = VisualMatcher(
        ReferenceLibrary.load(catalog, kind="hero"),
        VisualMatcherConfig(hero_scoring_backend="vectorized", vectorized_chunk_size=1),
    )

    assert matcher._vectorized_bank is not None
    assert all(
        np.shares_memory(prepared.aligned_gray, matcher._vectorized_bank.aligned_gray)
        for prepared in matcher._features
    )


def test_vectorized_hero_scoring_preserves_ties_thresholds_and_active_reference_filter(
    tmp_path: Path,
) -> None:
    image = _pattern((200, 45, 75), True)
    references = (
        VisualReference("hero_z", "Hero Z", "z_visual", "catalog", image),
        VisualReference("hero_a", "Hero A", "a_visual", "catalog", image.copy()),
    )
    library = ReferenceLibrary(references, kind="hero")
    scalar = VisualMatcher(library, VisualMatcherConfig(minimum_score=1.0, minimum_margin=0.0))
    vectorized = VisualMatcher(
        library,
        VisualMatcherConfig(
            minimum_score=1.0,
            minimum_margin=0.0,
            hero_scoring_backend="vectorized",
            vectorized_chunk_size=8,
        ),
    )
    crop = _crop(image, kind=FieldKind.HERO)

    _assert_scalar_vectorized_parity(scalar, vectorized, crop)
    assert vectorized.match_hero(crop).hero_id == "hero_a"
    filtered = vectorized.with_excluded_visual_ids(frozenset({"a_visual"}))
    assert filtered.match_hero(crop).hero_id == "hero_z"
    assert vectorized.match_hero(crop).hero_id == "hero_a"
    with pytest.raises(ValueError, match="cannot remove every"):
        vectorized.with_excluded_visual_ids(frozenset({"a_visual", "z_visual"}))


def test_vectorized_scoring_is_rejected_for_item_libraries(tmp_path: Path) -> None:
    catalog, _, _ = _catalog(tmp_path)
    with pytest.raises(ValueError, match="hero libraries only"):
        VisualMatcher(
            ReferenceLibrary.load(catalog, kind="item"),
            VisualMatcherConfig(hero_scoring_backend="vectorized"),
        )


def test_hero_preprocessing_can_be_limited_to_ally_side(tmp_path: Path) -> None:
    catalog, first, _ = _catalog(tmp_path)
    library = ReferenceLibrary.load(catalog, kind="hero")
    darkened = np.asarray(np.clip(first.astype(np.int16) - 35, 0, 255), dtype=np.uint8)
    matcher = VisualMatcher(
        library,
        VisualMatcherConfig(
            minimum_score=0.0,
            minimum_margin=0.0,
            hero_preprocessing_views=("clahe_luma", "gamma_085", "gamma_115", "unsharp"),
            hero_preprocessing_sides=("ally",),
            preprocessing_bonus_weight=0.45,
        ),
    )

    ally = matcher.match_hero(_crop(darkened, kind=FieldKind.HERO, side=TeamSide.ALLY))
    enemy = matcher.match_hero(_crop(darkened, kind=FieldKind.HERO, side=TeamSide.ENEMY))

    assert "preprocessing_gain" in ally.candidates[0].scores
    assert "preprocessing_gain" not in enemy.candidates[0].scores


def _acceptance_policy(tmp_path: Path, *, passed: bool = True) -> HeroAcceptancePolicy:
    path = tmp_path / "hero-acceptance-policy.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "minimum_score": 0.0,
                "default_margin": 0.018,
                "passed": passed,
                "policy": {
                    "side_margins": {"ally": 0.0, "enemy": 0.018},
                    "class_margins": {"ally:hero_a": 0.0},
                },
            }
        ),
        encoding="utf-8",
    )
    return HeroAcceptancePolicy.load(path)


def test_promoted_acceptance_policy_can_lower_ally_margin(tmp_path: Path) -> None:
    catalog, first, _ = _catalog(tmp_path)
    policy = _acceptance_policy(tmp_path)
    matcher = VisualMatcher(
        ReferenceLibrary.load(catalog, kind="hero"),
        VisualMatcherConfig(
            minimum_score=0.0,
            minimum_margin=1.0,
            hero_acceptance_policy=policy,
        ),
    )

    result = matcher.match_hero(_crop(first, kind=FieldKind.HERO))

    assert result.status is ExtractionStatus.OK
    assert result.hero_id == "hero_a"
    assert result.candidates[0].scores["acceptance_minimum_margin"] == 0.0


def test_unpromoted_acceptance_policy_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="did not pass promotion"):
        _acceptance_policy(tmp_path, passed=False)


def _reranker_policy(tmp_path: Path, *, passed: bool = True) -> HeroRerankerPolicy:
    path = tmp_path / "hero-reranker-policy.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "passed": passed,
                "feature_names": [
                    "catalog_minus_prototype",
                    "aligned_minus_prototype",
                    "color_minus_prototype",
                    "histogram_minus_prototype",
                    "edge_minus_prototype",
                    "preprocessing_gain",
                ],
                "coefficients": [1.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                "override_lead": 0.0,
                "top_n": 2,
                "only_abstained": True,
            }
        ),
        encoding="utf-8",
    )
    return HeroRerankerPolicy.load(path)


def test_promoted_reranker_can_override_with_bounded_candidate_evidence(
    tmp_path: Path,
) -> None:
    catalog, first, second = _catalog(tmp_path)
    matcher = VisualMatcher(
        ReferenceLibrary.load(catalog, kind="hero"),
        VisualMatcherConfig(
            minimum_margin=1.0,
            hero_reranker_policy=_reranker_policy(tmp_path),
        ),
    )
    ranked = [
        (
            VisualReference("hero_a", "Hero A", "a", "catalog", first),
            {"fused_similarity": 0.80, "prototype_similarity": 0.90, "catalog_similarity": 0.70},
        ),
        (
            VisualReference("hero_b", "Hero B", "b", "catalog", second),
            {"fused_similarity": 0.79, "prototype_similarity": 0.70, "catalog_similarity": 0.90},
        ),
    ]

    reranked = matcher._rerank_hero(ranked, _crop(first, kind=FieldKind.HERO))

    assert reranked[0][0].entity_id == "hero_b"
    assert reranked[0][1]["reranker_override"] == 1.0
    assert reranked[0][1]["reranker_margin"] > 0.0


def test_unpromoted_reranker_policy_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="did not pass promotion"):
        _reranker_policy(tmp_path, passed=False)


def _balanced_policy(
    tmp_path: Path,
    *,
    enabled: bool = True,
    minimum_votes: int = 3,
) -> HeroBalancedPolicy:
    path = tmp_path / "hero-balanced-policy.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "constrained_consensus",
                "mode": "balanced",
                "status": "operator_approved",
                "enabled": enabled,
                "catalog_sha256": "b" * 64,
                "prototype_manifest_sha256": "a" * 64,
                "beta": 0.4,
                "gamma": 0.55,
                "top_n": 3,
                "only_abstained": True,
                "gate": {
                    "minimum_prototype": 0.7,
                    "minimum_rank_margin": 0.01,
                    "minimum_prototype_margin": 0.01,
                    "minimum_votes": minimum_votes,
                },
            }
        ),
        encoding="utf-8",
    )
    return HeroBalancedPolicy.load(path)


def test_balanced_policy_uses_constrained_score_and_consensus_gate(tmp_path: Path) -> None:
    policy = _balanced_policy(tmp_path)
    winner = {
        "fused_similarity": 0.8,
        "prototype_similarity": 0.9,
        "catalog_similarity": 0.7,
        "preprocessing_gain": 0.02,
        "aligned_gray_correlation": 0.9,
        "color_correlation": 0.8,
        "histogram_correlation": 0.7,
        "edge_correlation": 0.6,
    }
    runner = {
        "fused_similarity": 0.79,
        "prototype_similarity": 0.8,
        "catalog_similarity": 0.75,
        "preprocessing_gain": 0.01,
        "aligned_gray_correlation": 0.8,
        "color_correlation": 0.7,
        "histogram_correlation": 0.6,
        "edge_correlation": 0.65,
    }

    winner_score = policy.score(winner)
    runner_score = policy.score(runner)

    assert winner_score == pytest.approx(0.6 * 0.9 + 0.4 * 0.7 - 0.55 * 0.02)
    assert policy.accepts(
        winner,
        runner,
        rank_margin=winner_score - runner_score,
    )


def test_balanced_policy_is_champion_protected_and_bounded(tmp_path: Path) -> None:
    catalog, first, second = _catalog(tmp_path)
    policy = _balanced_policy(tmp_path, minimum_votes=0)
    ranked = [
        (
            VisualReference("hero_a", "Hero A", "a", "catalog", first),
            {
                "fused_similarity": 0.80,
                "prototype_similarity": 0.80,
                "catalog_similarity": 0.80,
                "aligned_gray_correlation": 0.80,
                "color_correlation": 0.80,
                "histogram_correlation": 0.80,
                "edge_correlation": 0.80,
            },
        ),
        (
            VisualReference("hero_b", "Hero B", "b", "catalog", second),
            {
                "fused_similarity": 0.79,
                "prototype_similarity": 0.90,
                "catalog_similarity": 0.70,
                "aligned_gray_correlation": 0.90,
                "color_correlation": 0.90,
                "histogram_correlation": 0.90,
                "edge_correlation": 0.90,
            },
        ),
        (
            VisualReference("hero_c", "Hero C", "c", "catalog", second),
            {
                "fused_similarity": 0.60,
                "prototype_similarity": 0.60,
                "catalog_similarity": 0.60,
                "aligned_gray_correlation": 0.60,
                "color_correlation": 0.60,
                "histogram_correlation": 0.60,
                "edge_correlation": 0.60,
            },
        ),
    ]
    abstaining = VisualMatcher(
        ReferenceLibrary.load(catalog, kind="hero"),
        VisualMatcherConfig(minimum_margin=1.0, hero_balanced_policy=policy),
    )
    accepting = VisualMatcher(
        ReferenceLibrary.load(catalog, kind="hero"),
        VisualMatcherConfig(minimum_score=0.0, minimum_margin=0.0, hero_balanced_policy=policy),
    )

    reranked = abstaining._rerank_hero(ranked, _crop(first, kind=FieldKind.HERO))
    protected = accepting._rerank_hero(ranked, _crop(first, kind=FieldKind.HERO))

    assert reranked[0][0].entity_id == "hero_b"
    assert reranked[0][1]["balanced_policy_eligible"] == 1.0
    assert reranked[0][1]["balanced_policy_override"] == 1.0
    assert protected[0][0].entity_id == "hero_a"
    assert "balanced_policy_eligible" not in protected[0][1]


def test_disabled_balanced_policy_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not enabled"):
        _balanced_policy(tmp_path, enabled=False)


def test_balanced_policy_cannot_be_combined_with_other_policy_family(tmp_path: Path) -> None:
    acceptance = _acceptance_policy(tmp_path)
    with pytest.raises(ValueError, match="cannot be combined"):
        VisualMatcherConfig(
            hero_acceptance_policy=acceptance,
            hero_balanced_policy=_balanced_policy(tmp_path),
        )


def test_repository_hero_modes_resolve_balanced_default_and_fallbacks() -> None:
    catalog = ROOT / "catalogs/staging/user-approved-2026-08-01-r2/catalog.json"

    balanced = resolve_hero_recognition(
        project_root=ROOT,
        catalog_path=catalog,
    )
    strict = resolve_hero_recognition(
        project_root=ROOT,
        catalog_path=catalog,
        mode="strict",
    )
    original = resolve_hero_recognition(
        project_root=ROOT,
        catalog_path=catalog,
        mode="original",
    )

    assert balanced.mode == "balanced"
    assert balanced.matcher_config.hero_balanced_policy is not None
    assert strict.matcher_config.hero_acceptance_policy is not None
    assert strict.matcher_config.hero_reranker_policy is not None
    assert original.matcher_config.hero_balanced_policy is None
    assert original.matcher_config.hero_acceptance_policy is None
    assert original.matcher_config.hero_reranker_policy is None
    assert balanced.prototype_manifest == strict.prototype_manifest == original.prototype_manifest


def test_balanced_mode_rejects_catalog_hash_mismatch(tmp_path: Path) -> None:
    wrong_catalog = tmp_path / "catalog.json"
    wrong_catalog.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="catalog SHA-256 mismatch"):
        resolve_hero_recognition(project_root=ROOT, catalog_path=wrong_catalog)


def test_repository_item_recognition_resolves_reviewed_manifest() -> None:
    catalog = ROOT / "catalogs/staging/user-approved-2026-08-01-r2/catalog.json"
    setup = resolve_item_recognition(project_root=ROOT, catalog_path=catalog)

    assert setup.prototype_manifest == (
        ROOT / "data/private/recognition_prototypes/family-01-v1/item/manifest.json"
    )
    assert setup.manifest_sha256 == hashlib.sha256(
        setup.prototype_manifest.read_bytes()
    ).hexdigest()


def test_item_recognition_rejects_catalog_hash_mismatch(tmp_path: Path) -> None:
    wrong_catalog = tmp_path / "catalog.json"
    wrong_catalog.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="catalog SHA-256 mismatch"):
        resolve_item_recognition(project_root=ROOT, catalog_path=wrong_catalog)


def test_wrong_hero_prototype_cannot_override_exact_catalog_support(tmp_path: Path) -> None:
    catalog, first, _ = _catalog(tmp_path)
    prototype_root = tmp_path / "hero_prototypes"
    _write_rgb(prototype_root / "assets/wrong.png", first)
    manifest = prototype_root / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "kind": "hero",
                "references": [
                    {
                        "entity_id": "hero_b",
                        "name": "Hero B",
                        "visual_id": "wrong_style_match",
                        "asset_path": "assets/wrong.png",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    matcher = VisualMatcher(
        ReferenceLibrary.load(catalog, kind="hero", prototype_manifest=manifest),
        VisualMatcherConfig(minimum_score=0.6, minimum_margin=0.01),
    )

    result = matcher.match_hero(_crop(first, kind=FieldKind.HERO))

    assert result.status is ExtractionStatus.OK
    assert result.hero_id == "hero_a"
    wrong = next(candidate for candidate in result.candidates if candidate.candidate_id == "hero_b")
    assert "prototype_similarity" in wrong.scores
    assert "catalog_similarity" in wrong.scores


def test_prototype_manifest_rejects_entity_absent_from_catalog(tmp_path: Path) -> None:
    catalog, first, _ = _catalog(tmp_path)
    prototype_root = tmp_path / "stale_prototypes"
    _write_rgb(prototype_root / "assets/stale.png", first)
    manifest = prototype_root / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "kind": "hero",
                "references": [
                    {
                        "entity_id": "hero_removed_from_catalog",
                        "name": "Stale",
                        "visual_id": "stale",
                        "asset_path": "assets/stale.png",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="absent from the active catalog"):
        ReferenceLibrary.load(catalog, kind="hero", prototype_manifest=manifest)


def test_engine_registers_exact_prototype_manifest_hashes(tmp_path: Path) -> None:
    catalog, first, _ = _catalog(tmp_path)
    manifests: dict[str, Path] = {}
    for kind, entity_id in (("hero", "hero_a"), ("item", "item_a")):
        root = tmp_path / f"{kind}_prototypes"
        _write_rgb(root / "assets/reference.png", first)
        manifest = root / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "kind": kind,
                    "references": [
                        {
                            "entity_id": entity_id,
                            "name": entity_id,
                            "visual_id": f"{kind}_reference",
                            "asset_path": "assets/reference.png",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        manifests[kind] = manifest

    engine = NexusV2Engine(
        profiles_root=ROOT / "profiles",
        catalog_path=catalog,
        hero_prototypes=manifests["hero"],
        item_prototypes=manifests["item"],
    )

    assert (
        engine.visual_model_versions["hero_prototype_manifest_sha256"]
        == hashlib.sha256(manifests["hero"].read_bytes()).hexdigest()
    )
    assert (
        engine.visual_model_versions["item_prototype_manifest_sha256"]
        == hashlib.sha256(manifests["item"].read_bytes()).hexdigest()
    )


def test_engine_registers_opt_in_hero_preprocessing_provenance(tmp_path: Path) -> None:
    catalog, _, _ = _catalog(tmp_path)
    config = VisualMatcherConfig(
        hero_preprocessing_views=("clahe_luma", "gamma_085"),
        preprocessing_bonus_weight=0.45,
        preprocessing_rerank_top_n=5,
    )

    engine = NexusV2Engine(
        profiles_root=ROOT / "profiles",
        catalog_path=catalog,
        hero_matcher_config=config,
    )

    assert engine.hero_matcher.config == config
    assert json.loads(engine.visual_model_versions["hero_preprocessing"]) == {
        "bonus_weight": 0.45,
        "rerank_top_n": 5,
        "sides": ["ally", "enemy"],
        "views": ["clahe_luma", "gamma_085"],
    }


def test_visual_matcher_returns_stable_item_id(tmp_path: Path) -> None:
    catalog, _, second = _catalog(tmp_path)
    library = ReferenceLibrary.load(catalog, kind="item")
    matcher = VisualMatcher(library, VisualMatcherConfig(minimum_score=0.6, minimum_margin=0.01))
    result = matcher.match_item(_crop(second, kind=FieldKind.ITEM, slot=6))
    assert result.status is ExtractionStatus.OK
    assert result.slot == 6
    assert result.item_id == "item_b"


def test_item_empty_prototype_emits_empty_without_hiding_occupied_item(tmp_path: Path) -> None:
    catalog, occupied, _ = _catalog(tmp_path)
    rng = np.random.default_rng(7)
    empty = np.asarray(
        np.clip(
            np.full((64, 64, 3), (10, 25, 55), dtype=np.int16)
            + rng.integers(-4, 5, size=(64, 64, 1)),
            0,
            255,
        ),
        dtype=np.uint8,
    )
    prototype_root = tmp_path / "prototypes"
    _write_rgb(prototype_root / "assets/empty.png", empty)
    manifest = prototype_root / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "kind": "item",
                "references": [
                    {
                        "entity_id": None,
                        "name": None,
                        "visual_id": "empty_slot",
                        "asset_path": "assets/empty.png",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    matcher = VisualMatcher(
        ReferenceLibrary.load(catalog, kind="item", prototype_manifest=manifest),
        VisualMatcherConfig(minimum_score=0.6, minimum_margin=0.01),
    )

    empty_result = matcher.match_item(_crop(empty, kind=FieldKind.ITEM, slot=0))
    occupied_result = matcher.match_item(_crop(occupied, kind=FieldKind.ITEM, slot=1))

    assert empty_result.status is ExtractionStatus.EMPTY
    assert empty_result.item_id is None
    assert occupied_result.status is ExtractionStatus.OK
    assert occupied_result.item_id == "item_a"


def test_item_occupancy_gate_emits_empty_without_prototype_manifest(tmp_path: Path) -> None:
    catalog, _, _ = _catalog(tmp_path)
    matcher = VisualMatcher(ReferenceLibrary.load(catalog, kind="item"))
    empty = np.full((64, 64, 3), (10, 25, 55), dtype=np.uint8)
    ambiguous = np.full((64, 64, 3), (90, 90, 90), dtype=np.uint8)

    empty_result = matcher.match_item(_crop(empty, kind=FieldKind.ITEM, slot=4))
    ambiguous_result = matcher.match_item(_crop(ambiguous, kind=FieldKind.ITEM, slot=5))

    assert empty_result.status is ExtractionStatus.EMPTY
    assert empty_result.candidates[0].label == "EMPTY"
    assert ambiguous_result.status is not ExtractionStatus.EMPTY
    assert ambiguous_result.candidates[0].label == "OCCUPANCY_UNCERTAIN"
