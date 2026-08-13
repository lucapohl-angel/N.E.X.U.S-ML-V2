from __future__ import annotations

from typing import cast

import numpy as np
from numpy.typing import NDArray

from nexus_v2.engine import NexusV2Engine
from nexus_v2.layout.cropper import SemanticCrop
from nexus_v2.layout.profiles import FieldKind, ScreenType, TeamSide
from nexus_v2.ocr import LocalOCRPipeline, OCRCandidate
from nexus_v2.recognition import VisualMatcher
from nexus_v2.schemas.result import ConfidenceSemantics, ExtractionStatus, HeroResult


class NoopOCRBackend:
    name = "noop"

    def recognize(self, image: NDArray[np.uint8], *, parser: str) -> OCRCandidate | None:
        del image, parser
        return None


class CountingHeroMatcher:
    def __init__(self) -> None:
        self.calls = 0

    def match_hero(self, crop: SemanticCrop) -> HeroResult:
        self.calls += 1
        return HeroResult(
            hero_id="hero_test",
            name="Test",
            status=ExtractionStatus.OK,
            confidence=0.9,
            confidence_semantics=ConfidenceSemantics.TEMPLATE_SIMILARITY,
            source_box=crop.tight_box,
        )


def _hero_crop(*, side: TeamSide, box: tuple[int, int, int, int]) -> SemanticCrop:
    image = np.zeros((20, 20, 3), dtype=np.uint8)
    return SemanticCrop(
        field_id="hero",
        kind=FieldKind.HERO,
        screen_type=ScreenType.OVERALL,
        side=side,
        row=0,
        slot=None,
        parser=None,
        tight_box=box,
        context_box=box,
        tight_rgb=image,
        context_rgb=image,
        mask=None,
        clipped=False,
    )


def test_hero_memo_reuses_exact_inputs_and_preserves_current_source_box() -> None:
    engine = object.__new__(NexusV2Engine)
    matcher = CountingHeroMatcher()
    engine.hero_matcher = cast(VisualMatcher, matcher)
    engine.ocr = LocalOCRPipeline((NoopOCRBackend(),))
    engine._hero_inference_memo = None
    first_crop = _hero_crop(side=TeamSide.ALLY, box=(0, 0, 20, 20))
    repeated_crop = _hero_crop(side=TeamSide.ALLY, box=(10, 10, 30, 30))

    with engine._match_inference_scope():
        first = engine._match_hero(first_crop)
        repeated = engine._match_hero(repeated_crop)

    assert matcher.calls == 1
    assert first.source_box == first_crop.tight_box
    assert repeated.source_box == repeated_crop.tight_box
    assert repeated.model_copy(update={"source_box": first.source_box}) == first
    assert engine._hero_inference_memo is None

    with engine._match_inference_scope():
        engine._match_hero(first_crop)

    assert matcher.calls == 2


def test_hero_memo_includes_team_side() -> None:
    engine = object.__new__(NexusV2Engine)
    matcher = CountingHeroMatcher()
    engine.hero_matcher = cast(VisualMatcher, matcher)
    engine.ocr = LocalOCRPipeline((NoopOCRBackend(),))
    engine._hero_inference_memo = None

    with engine._match_inference_scope():
        engine._match_hero(_hero_crop(side=TeamSide.ALLY, box=(0, 0, 20, 20)))
        engine._match_hero(_hero_crop(side=TeamSide.ENEMY, box=(0, 0, 20, 20)))

    assert matcher.calls == 2
