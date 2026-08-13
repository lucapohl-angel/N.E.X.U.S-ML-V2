from __future__ import annotations

import numpy as np
import pytest
from numpy.typing import NDArray

from nexus_v2.layout.cropper import SemanticCrop
from nexus_v2.layout.profiles import FieldKind, ScreenType, TeamSide
from nexus_v2.ocr import LocalOCRPipeline, OCRCandidate, parse_ocr
from nexus_v2.ocr.local import RapidOCRBackend
from nexus_v2.ocr.preprocess import build_ocr_variants
from nexus_v2.schemas.result import ExtractionStatus


class FixedBackend:
    name = "fixed"

    def __init__(self, raw: str, confidence: float = 0.8) -> None:
        self.raw = raw
        self.confidence = confidence

    def recognize(self, image: NDArray[np.uint8], *, parser: str) -> OCRCandidate | None:
        del image, parser
        return OCRCandidate(
            raw=self.raw,
            confidence=self.confidence,
            backend=self.name,
            preprocessing="input",
        )


class RapidFixedBackend(FixedBackend):
    name = "rapidocr-onnxruntime"


class CapturingRapidBackend(RapidFixedBackend):
    def __init__(self, raw: str, confidence: float = 0.8) -> None:
        super().__init__(raw, confidence)
        self.widths: list[int] = []

    def recognize(self, image: NDArray[np.uint8], *, parser: str) -> OCRCandidate | None:
        self.widths.append(image.shape[1])
        return super().recognize(image, parser=parser)


class WidthMappedRapidBackend:
    name = "rapidocr-onnxruntime"

    def __init__(
        self,
        values: dict[int, tuple[str, float] | None],
        *,
        default: tuple[str, float] | None = None,
    ) -> None:
        self.values = values
        self.default = default
        self.widths: list[int] = []

    def recognize(self, image: NDArray[np.uint8], *, parser: str) -> OCRCandidate | None:
        del parser
        width = image.shape[1]
        self.widths.append(width)
        value = self.values.get(width, self.default)
        if value is None:
            return None
        raw, confidence = value
        return OCRCandidate(
            raw=raw,
            confidence=confidence,
            backend=self.name,
            preprocessing="input",
        )


def _crop(parser: str, *, field_id: str = "test", width: int = 28) -> SemanticCrop:
    image = np.zeros((12, width, 3), dtype=np.uint8)
    return SemanticCrop(
        field_id=field_id,
        kind=FieldKind.OCR,
        screen_type=ScreenType.OVERALL,
        side=TeamSide.ALLY,
        row=0,
        slot=None,
        parser=parser,
        tight_box=(10, 20, 10 + width, 32),
        context_box=(8, 18, 12 + width, 34),
        tight_rgb=image,
        context_rgb=image,
        mask=None,
        clipped=False,
    )


def test_exact_input_memo_is_scoped_to_one_match() -> None:
    backend = CapturingRapidBackend("12")
    pipeline = LocalOCRPipeline((backend,))
    crop = _crop("short_integer")

    with pipeline.inference_memo_scope():
        first = pipeline.extract(crop)
        second = pipeline.extract(crop)

    assert first == second
    assert len(backend.widths) == 1

    with pipeline.inference_memo_scope():
        assert pipeline.extract(crop) == first

    assert len(backend.widths) == 2


def test_exact_input_memo_includes_parser_and_rejects_nested_scopes() -> None:
    backend = CapturingRapidBackend("12")
    pipeline = LocalOCRPipeline((backend,))

    with pipeline.inference_memo_scope():
        pipeline.extract(_crop("short_integer"))
        pipeline.extract(_crop("small_integer"))
        with pytest.raises(RuntimeError, match="cannot be nested"), pipeline.inference_memo_scope():
            pass

    assert len(backend.widths) == 2


def test_semantic_parsers_are_conservative_and_typed() -> None:
    assert parse_ocr("O7", parser="small_integer").value == 7
    assert parse_ocr("07", parser="short_integer").value == 7
    assert parse_ocr("1.1", parser="level").value == 11
    assert parse_ocr("123456789012345678", parser="battle_id_18").value == "123456789012345678"
    assert parse_ocr("52%", parser="percentage").value == 52
    assert parse_ocr("9,8", parser="decimal").value == 9.8
    assert parse_ocr("18:59", parser="duration").value == "18:59"
    assert parse_ocr("2026/08/01 19:45", parser="datetime").value == "2026-08-01 19:45"
    assert parse_ocr("08/01/202619:45:16", parser="datetime").value == "2026-08-01 19:45:16"
    assert parse_ocr("Victory", parser="result").value == "VICTORY"


def test_semantic_parsers_reject_impossible_values() -> None:
    assert not parse_ocr("16", parser="level").valid
    assert not parse_ocr("11123456789012345678", parser="battle_id_18").valid
    assert not parse_ocr("101%", parser="percentage").valid
    assert not parse_ocr("18:72", parser="duration").valid
    assert not parse_ocr("not a date", parser="datetime").valid


def test_local_pipeline_returns_validated_value_and_evidence() -> None:
    result = LocalOCRPipeline((FixedBackend("42%"),)).extract(_crop("percentage"))
    assert result.status is ExtractionStatus.OK
    assert result.value == 42
    assert result.source_box == (10, 20, 38, 32)
    assert result.candidates
    assert result.confidence is not None


def test_percentage_pipeline_keeps_full_crop_and_adds_right_edge_variants() -> None:
    backend = CapturingRapidBackend("42%")
    result = LocalOCRPipeline((backend,)).extract(_crop("percentage", width=120))

    assert result.status is ExtractionStatus.OK
    assert backend.widths == [120, 80, 240]
    candidate_ids = {candidate.candidate_id for candidate in result.candidates}
    assert "rapidocr-onnxruntime:right80-native" in candidate_ids
    assert "rapidocr-onnxruntime:right80-cubic3x" in candidate_ids


def test_white_glyph_variants_are_level_specific() -> None:
    image = np.zeros((20, 40, 3), dtype=np.uint8)
    level_names = {variant.name for variant in build_ocr_variants(image, parser="level")}
    integer_names = {variant.name for variant in build_ocr_variants(image, parser="short_integer")}

    assert {"white_glyph3x", "white_glyph3x_inverted"} <= level_names
    assert "white_glyph3x" not in integer_names


def test_local_pipeline_abstains_when_every_candidate_is_invalid() -> None:
    result = LocalOCRPipeline((FixedBackend("999%"),)).extract(_crop("percentage"))
    assert result.status is ExtractionStatus.UNKNOWN
    assert result.value is None
    assert "percentage_out_of_range" in result.validation_messages


def test_full_ensemble_field_accepts_a_semantically_valid_value() -> None:
    backend = RapidFixedBackend("1234", confidence=0.9)
    result = LocalOCRPipeline((backend,)).extract(_crop("large_integer", field_id="turret_damage"))
    assert result.status is ExtractionStatus.OK
    assert result.value == 1234
    assert result.raw == "1234"
    assert result.candidates


def test_level_policy_prefers_longer_valid_normalized_candidate() -> None:
    backend = WidthMappedRapidBackend({28: ("5", 0.99), 84: ("15", 0.7)})
    result = LocalOCRPipeline((backend,)).extract(_crop("level", field_id="level"))

    assert result.status is ExtractionStatus.OK
    assert result.value == 15
    assert "ocr_selection_route:longest_normalized" in result.validation_messages


def test_jungle_percentage_policy_uses_right_edge_candidates_only() -> None:
    backend = WidthMappedRapidBackend(
        {
            120: ("72%", 0.99),
            360: ("72%", 0.99),
            80: ("42%", 0.7),
            240: ("42%", 0.7),
        }
    )
    result = LocalOCRPipeline((backend,)).extract(
        _crop("percentage", field_id="jungle_gold_percent", width=120)
    )

    assert result.status is ExtractionStatus.OK
    assert result.value == 42
    assert "ocr_selection_route:right_edge_only" in result.validation_messages


def test_reviewed_abstention_fields_use_the_full_variant_ensemble() -> None:
    backend = WidthMappedRapidBackend({28: None, 84: ("4", 0.7)})
    result = LocalOCRPipeline((backend,)).extract(
        _crop("small_integer", field_id="consecutive_kills")
    )

    assert result.status is ExtractionStatus.OK
    assert result.value == 4
    assert len(backend.widths) > 1


class RecordingRapidEngine:
    def __init__(self) -> None:
        self.detection_flags: list[bool] = []

    def __call__(
        self,
        image: NDArray[np.uint8],
        *,
        use_det: bool,
        use_cls: bool,
        use_rec: bool,
    ) -> object:
        del image, use_cls, use_rec
        self.detection_flags.append(use_det)
        return ([["2026/08/10", 0.95]], None)


@pytest.mark.parametrize(("text_detection", "expected"), [(True, True), (False, False)])
def test_rapidocr_profile_controls_detection_for_localized_metadata(
    text_detection: bool,
    expected: bool,
) -> None:
    engine = RecordingRapidEngine()
    backend = RapidOCRBackend.__new__(RapidOCRBackend)
    backend._engine = engine
    backend.text_detection = text_detection
    backend.use_cuda = False

    result = backend.recognize(np.zeros((16, 80, 3), dtype=np.uint8), parser="datetime")

    assert result is not None
    assert engine.detection_flags == [expected]
