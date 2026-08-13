"""Validated local OCR ensemble with explicit abstention on unresolved conflicts."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace

import numpy as np
from numpy.typing import NDArray

from nexus_v2.layout.cropper import SemanticCrop
from nexus_v2.ocr.normalize import ParsedOCR, parse_ocr
from nexus_v2.ocr.preprocess import OCRVariant, build_ocr_variants
from nexus_v2.ocr.types import OCRBackend, OCRCandidate
from nexus_v2.schemas.result import (
    CandidateEvidence,
    ConfidenceSemantics,
    ExtractedField,
    ExtractionStatus,
)

OCR_SELECTION_POLICY_VERSION = "reviewed-field-routing-v1"
_FULL_ENSEMBLE_FIELDS = frozenset(
    {
        "consecutive_kills",
        "crowd_control",
        "healing_and_shields",
        "jungle_gold",
        "jungle_gold_percent",
        "turret_damage",
    }
)
_LONGEST_NORMALIZED_FIELDS = frozenset({"level"})
_RIGHT_EDGE_ONLY_FIELDS = frozenset({"jungle_gold_percent"})


class LocalOCRPipeline:
    selection_policy_version = OCR_SELECTION_POLICY_VERSION

    def __init__(
        self,
        backends: tuple[OCRBackend, ...],
        *,
        vision_fallback: OCRBackend | None = None,
        always_fallback_fields: frozenset[str] = frozenset({"player_name"}),
    ) -> None:
        if not backends:
            raise ValueError("at least one OCR backend is required")
        self.backends = backends
        self.vision_fallback = vision_fallback
        self.always_fallback_fields = always_fallback_fields
        self._inference_memo: (
            dict[tuple[int, str, tuple[int, ...], str, bytes], OCRCandidate | None] | None
        ) = None

    @contextmanager
    def inference_memo_scope(self) -> Iterator[None]:
        """Reuse exact backend inputs only for the lifetime of one match extraction."""

        if self._inference_memo is not None:
            raise RuntimeError("OCR inference memo scopes cannot be nested")
        self._inference_memo = {}
        try:
            yield
        finally:
            self._inference_memo = None

    def _recognize(
        self,
        backend: OCRBackend,
        image: NDArray[np.uint8],
        *,
        parser: str,
    ) -> OCRCandidate | None:
        memo = self._inference_memo
        if memo is None:
            return backend.recognize(image, parser=parser)
        key = (
            id(backend),
            parser,
            image.shape,
            image.dtype.str,
            hashlib.sha256(image.tobytes()).digest(),
        )
        if key not in memo:
            memo[key] = backend.recognize(image, parser=parser)
        return memo[key]

    def extract(self, crop: SemanticCrop) -> ExtractedField:
        local = self._extract_local(crop)
        if self.vision_fallback is None or crop.parser is None:
            return local
        should_fallback = (
            crop.field_id in self.always_fallback_fields or local.status is not ExtractionStatus.OK
        )
        if not should_fallback:
            return local
        candidate = self.vision_fallback.recognize(crop.tight_rgb, parser=crop.parser)
        if candidate is None:
            return local.model_copy(
                update={
                    "validation_messages": tuple(
                        (*local.validation_messages, "vision_fallback_failed")
                    )
                }
            )
        parsed = parse_ocr(candidate.raw, parser=crop.parser)
        fallback_evidence = CandidateEvidence(
            candidate_id=f"{candidate.backend}:{candidate.preprocessing}",
            raw=candidate.raw,
            scores={"semantic_validation": 1.0 if parsed.valid else 0.0},
        )
        if not parsed.valid:
            return local.model_copy(
                update={
                    "candidates": tuple((*local.candidates, fallback_evidence))[:12],
                    "validation_messages": tuple(
                        (*local.validation_messages, *parsed.messages, "vision_fallback_invalid")
                    ),
                }
            )
        return ExtractedField(
            raw=candidate.raw,
            value=parsed.value,
            status=ExtractionStatus.OK,
            confidence=None,
            confidence_semantics=None,
            source_box=crop.tight_box,
            candidates=tuple((*local.candidates, fallback_evidence))[:12],
            validation_messages=("opt_in_vision_fallback_used",),
        )

    def _extract_local(self, crop: SemanticCrop) -> ExtractedField:
        if crop.parser is None:
            return ExtractedField(
                status=ExtractionStatus.UNSUPPORTED,
                source_box=crop.tight_box,
                validation_messages=("semantic field has no OCR parser",),
            )
        observations: list[tuple[OCRCandidate, ParsedOCR]] = []
        variants = build_ocr_variants(crop.tight_rgb, parser=crop.parser)
        percentage_variants: tuple[OCRVariant, ...] = ()
        if crop.parser == "percentage":
            right_edge = crop.tight_rgb[:, max(0, crop.tight_rgb.shape[1] - 80) :]
            right_edge_variants = build_ocr_variants(right_edge, parser=crop.parser)
            percentage_variants = (
                OCRVariant(name="right80-native", image=right_edge_variants[0].image),
                OCRVariant(name="right80-cubic3x", image=right_edge_variants[1].image),
            )
        rapid_available = any(backend.name == "rapidocr-onnxruntime" for backend in self.backends)
        full_ensemble_field = (
            crop.parser
            in {
                "battle_id",
                "battle_id_18",
                "datetime",
                "level",
            }
            or crop.field_id in _FULL_ENSEMBLE_FIELDS
        )
        for backend in self.backends:
            if rapid_available and not full_ensemble_field and backend.name == "tesseract":
                continue
            if backend.name == "rapidocr-onnxruntime":
                selected_variants = (
                    (*variants, *percentage_variants)
                    if full_ensemble_field
                    else (variants[0], *percentage_variants)
                )
            else:
                selected_variants = tuple(
                    variant for variant in variants if variant.name in {"cubic3x", "clahe3x"}
                )
            for variant in selected_variants:
                candidate = self._recognize(backend, variant.image, parser=crop.parser)
                if candidate is None:
                    continue
                candidate = replace(candidate, preprocessing=variant.name)
                observations.append((candidate, parse_ocr(candidate.raw, parser=crop.parser)))
        evidence = tuple(
            CandidateEvidence(
                candidate_id=f"{candidate.backend}:{candidate.preprocessing}",
                raw=candidate.raw,
                scores={
                    "ocr_sequence_confidence": float(np.clip(candidate.confidence, 0.0, 1.0)),
                    "semantic_validation": 1.0 if parsed.valid else 0.0,
                },
            )
            for candidate, parsed in sorted(
                observations,
                key=lambda item: (-item[0].confidence, item[0].backend, item[0].preprocessing),
            )[:8]
        )
        valid = [(candidate, parsed) for candidate, parsed in observations if parsed.valid]
        selection_route = "confidence_support"
        if crop.field_id in _RIGHT_EDGE_ONLY_FIELDS:
            right_edge_valid = [
                (candidate, parsed)
                for candidate, parsed in valid
                if candidate.preprocessing.startswith("right80-")
            ]
            if right_edge_valid:
                valid = right_edge_valid
                selection_route = "right_edge_only"
        if not valid:
            messages = tuple(
                sorted({message for _, parsed in observations for message in parsed.messages})
            ) or ("no_local_ocr_candidate",)
            return ExtractedField(
                raw=observations[0][0].raw if observations else None,
                status=ExtractionStatus.UNKNOWN,
                source_box=crop.tight_box,
                candidates=evidence,
                validation_messages=messages,
            )

        groups: dict[str, list[tuple[OCRCandidate, ParsedOCR]]] = defaultdict(list)
        for candidate, parsed in valid:
            groups[parsed.normalized].append((candidate, parsed))
        ranked: list[tuple[float, str, OCRCandidate, ParsedOCR]] = []
        for normalized, members in groups.items():
            best_candidate, best_parsed = max(
                members, key=lambda item: (item[0].confidence, item[0].backend)
            )
            score = float(np.clip(best_candidate.confidence + 0.05 * (len(members) - 1), 0.0, 1.0))
            ranked.append((score, normalized, best_candidate, best_parsed))
        if crop.field_id in _LONGEST_NORMALIZED_FIELDS:
            ranked.sort(key=lambda item: (-len(item[1]), -item[0], item[1]))
            selection_route = "longest_normalized"
        else:
            ranked.sort(key=lambda item: (-item[0], item[1]))
        best_score, _, best_candidate, best_parsed = ranked[0]
        selected_id = f"{best_candidate.backend}:{best_candidate.preprocessing}"
        if not any(
            candidate.candidate_id == selected_id and candidate.raw == best_candidate.raw
            for candidate in evidence
        ):
            selected_evidence = CandidateEvidence(
                candidate_id=selected_id,
                raw=best_candidate.raw,
                scores={
                    "ocr_sequence_confidence": float(np.clip(best_candidate.confidence, 0.0, 1.0)),
                    "semantic_validation": 1.0,
                    "selected_by_policy": 1.0,
                },
            )
            evidence = tuple((*evidence[:7], selected_evidence))
        semantically_constrained = crop.parser not in {"player_name"}
        if not semantically_constrained and len(ranked) > 1 and best_score - ranked[1][0] < 0.025:
            return ExtractedField(
                raw=best_candidate.raw,
                status=ExtractionStatus.CONFLICT,
                confidence=best_score,
                confidence_semantics=ConfidenceSemantics.OCR_SEQUENCE,
                source_box=crop.tight_box,
                candidates=evidence,
                validation_messages=("local_ocr_candidates_conflict",),
            )
        validation_messages: list[str] = []
        if semantically_constrained and len(ranked) > 1:
            validation_messages.append("constrained_candidate_selected")
        if selection_route != "confidence_support":
            validation_messages.append(f"ocr_selection_route:{selection_route}")
        return ExtractedField(
            raw=best_candidate.raw,
            value=best_parsed.value,
            status=ExtractionStatus.OK,
            confidence=best_score,
            confidence_semantics=ConfidenceSemantics.OCR_SEQUENCE,
            source_box=crop.tight_box,
            candidates=evidence,
            validation_messages=tuple(validation_messages),
        )


__all__ = ["LocalOCRPipeline", "OCR_SELECTION_POLICY_VERSION"]
