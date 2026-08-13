"""Executable V2 vertical slice: decode, solve, crop, recognize, and OCR."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from pathlib import Path
from time import perf_counter

from nexus_v2.input import DecodedImage, ImageDecoder, ImageQuality, analyze_quality
from nexus_v2.input.decoder import ImageSource
from nexus_v2.layout import (
    GeometryResult,
    ProfileRegistry,
    SemanticCrop,
    build_semantic_crops,
    solve_geometry,
)
from nexus_v2.layout.profiles import FieldKind, TeamSide
from nexus_v2.ocr import LocalOCRPipeline, RapidOCRBackend, TesseractBackend
from nexus_v2.recognition import ReferenceLibrary, VisualMatcher, VisualMatcherConfig
from nexus_v2.schemas.result import (
    ConfidenceSemantics,
    ExtractedField,
    ExtractionResult,
    ExtractionStatus,
    GeometryEvidence,
    HeroResult,
    ItemResult,
    PlayerResult,
    Provenance,
    QualityEvidence,
    Resolution,
    SourceEvidence,
    TeamResult,
)

FLORYN_ID = "hero_0112"
FLOWER_OF_HOPE_ID = "item_a32997735166"


@dataclass
class _PlayerAccumulator:
    hero: HeroResult | None = None
    items: list[ItemResult] = dataclass_field(default_factory=list)
    fields: dict[str, ExtractedField] = dataclass_field(default_factory=dict)


@dataclass(frozen=True)
class ExtractionArtifacts:
    """Native extraction intermediates for callers that need crop-addressable evidence."""

    image: DecodedImage
    geometry: GeometryResult | None
    crops: tuple[SemanticCrop, ...]


class NexusV2Engine:
    def __init__(
        self,
        *,
        profiles_root: Path,
        catalog_path: Path,
        hero_prototypes: Path | None = None,
        item_prototypes: Path | None = None,
        hero_matcher_config: VisualMatcherConfig | None = None,
        use_rapidocr: bool = False,
        rapidocr_text_detection: bool = True,
        rapidocr_use_cuda: bool = False,
        rapidocr_intra_op_num_threads: int | None = None,
        rapidocr_inter_op_num_threads: int | None = None,
        runtime_versions: dict[str, str] | None = None,
    ) -> None:
        self.registry = ProfileRegistry.load(profiles_root)
        self.catalog_path = catalog_path.resolve()
        catalog = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        self.catalog_version = str(catalog["catalog_version"])
        self.visual_model_versions = {
            "visual_matcher": "masked-aligned-class-fusion-occupancy-seven-item-v5"
        }
        if runtime_versions is not None:
            self.visual_model_versions.update(runtime_versions)
        if hero_prototypes is not None:
            self.visual_model_versions["hero_prototype_manifest_sha256"] = hashlib.sha256(
                hero_prototypes.read_bytes()
            ).hexdigest()
        if item_prototypes is not None:
            self.visual_model_versions["item_prototype_manifest_sha256"] = hashlib.sha256(
                item_prototypes.read_bytes()
            ).hexdigest()
        resolved_hero_config = hero_matcher_config or VisualMatcherConfig()
        self.visual_model_versions["hero_scoring_backend"] = (
            resolved_hero_config.hero_scoring_backend
        )
        if resolved_hero_config.hero_scoring_backend == "vectorized":
            self.visual_model_versions["hero_vectorized_chunk_size"] = str(
                resolved_hero_config.vectorized_chunk_size
            )
            self.visual_model_versions["hero_vectorized_scalar_refine_top_n"] = str(
                resolved_hero_config.vectorized_scalar_refine_top_n
            )
        if resolved_hero_config.hero_preprocessing_views:
            self.visual_model_versions["hero_preprocessing"] = json.dumps(
                {
                    "views": resolved_hero_config.hero_preprocessing_views,
                    "sides": resolved_hero_config.hero_preprocessing_sides,
                    "bonus_weight": resolved_hero_config.preprocessing_bonus_weight,
                    "rerank_top_n": resolved_hero_config.preprocessing_rerank_top_n,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        if resolved_hero_config.hero_acceptance_policy is not None:
            self.visual_model_versions["hero_acceptance_policy_sha256"] = (
                resolved_hero_config.hero_acceptance_policy.manifest_sha256
            )
        if resolved_hero_config.hero_reranker_policy is not None:
            self.visual_model_versions["hero_reranker_policy_sha256"] = (
                resolved_hero_config.hero_reranker_policy.manifest_sha256
            )
        if resolved_hero_config.hero_balanced_policy is not None:
            self.visual_model_versions["hero_recognition_mode"] = "balanced"
            self.visual_model_versions["hero_balanced_policy_sha256"] = (
                resolved_hero_config.hero_balanced_policy.manifest_sha256
            )
        self.hero_matcher = VisualMatcher(
            ReferenceLibrary.load(
                self.catalog_path, kind="hero", prototype_manifest=hero_prototypes
            ),
            resolved_hero_config,
        )
        self.item_matcher = VisualMatcher(
            ReferenceLibrary.load(
                self.catalog_path, kind="item", prototype_manifest=item_prototypes
            )
        )
        ocr_backends = (
            (
                RapidOCRBackend(
                    text_detection=rapidocr_text_detection,
                    use_cuda=rapidocr_use_cuda,
                    intra_op_num_threads=rapidocr_intra_op_num_threads,
                    inter_op_num_threads=rapidocr_inter_op_num_threads,
                ),
            )
            if use_rapidocr
            else (TesseractBackend(),)
        )
        self.ocr = LocalOCRPipeline(ocr_backends)
        self.decoder = ImageDecoder()
        self.ocr_backend_names = tuple(backend.name for backend in ocr_backends)
        self._hero_inference_memo: (
            dict[tuple[str, tuple[int, ...], str, bytes], HeroResult] | None
        ) = None

    @contextmanager
    def _match_inference_scope(self) -> Iterator[None]:
        if self._hero_inference_memo is not None:
            raise RuntimeError("match inference memo scopes cannot be nested")
        self._hero_inference_memo = {}
        try:
            with self.ocr.inference_memo_scope():
                yield
        finally:
            self._hero_inference_memo = None

    def _match_hero(self, crop: SemanticCrop) -> HeroResult:
        memo = self._hero_inference_memo
        if memo is None:
            return self.hero_matcher.match_hero(crop)
        key = (
            crop.side.value if crop.side is not None else "",
            crop.tight_rgb.shape,
            crop.tight_rgb.dtype.str,
            hashlib.sha256(crop.tight_rgb.tobytes()).digest(),
        )
        cached = memo.get(key)
        if cached is None:
            cached = self.hero_matcher.match_hero(crop)
            memo[key] = cached
        if cached.source_box == crop.tight_box:
            return cached
        return cached.model_copy(update={"source_box": crop.tight_box})

    def extract(
        self,
        source: ImageSource,
        *,
        field_kinds: frozenset[FieldKind] | None = None,
        _artifact_sink: Callable[[ExtractionArtifacts], None] | None = None,
    ) -> ExtractionResult:
        started = perf_counter()
        image = self.decoder.decode(source)
        quality = analyze_quality(image)
        if quality.status is not ExtractionStatus.OK:
            if _artifact_sink is not None:
                _artifact_sink(ExtractionArtifacts(image=image, geometry=None, crops=()))
            return self._early_result(
                status=quality.status,
                image_width=image.width,
                image_height=image.height,
                quality=quality,
                started=started,
                warning=";".join(quality.reasons),
            )
        geometry = solve_geometry(image, self.registry)
        if geometry.status is not ExtractionStatus.OK or geometry.profile_id is None:
            if _artifact_sink is not None:
                _artifact_sink(ExtractionArtifacts(image=image, geometry=geometry, crops=()))
            return self._early_result(
                status=geometry.status,
                image_width=image.width,
                image_height=image.height,
                quality=quality,
                started=started,
                warning=";".join(geometry.reasons),
                viewport=geometry.viewport.box if geometry.viewport else None,
            )
        loaded = self.registry.get(geometry.profile_id)
        crops = build_semantic_crops(image, loaded, geometry)
        if _artifact_sink is not None:
            _artifact_sink(ExtractionArtifacts(image=image, geometry=geometry, crops=crops))
        players: dict[tuple[TeamSide, int], _PlayerAccumulator] = defaultdict(_PlayerAccumulator)
        metadata: dict[str, ExtractedField] = {}
        for crop in crops:
            if field_kinds is not None and crop.kind not in field_kinds:
                continue
            if crop.kind is FieldKind.HERO:
                if crop.side is None or crop.row is None:
                    continue
                players[(crop.side, crop.row)].hero = self._match_hero(crop)
            elif crop.kind is FieldKind.ITEM:
                if crop.side is None or crop.row is None:
                    continue
                players[(crop.side, crop.row)].items.append(self.item_matcher.match_item(crop))
            elif crop.kind in {FieldKind.OCR, FieldKind.METADATA}:
                result = self.ocr.extract(crop)
                if crop.side is None:
                    metadata[crop.field_id] = result
                elif crop.row is not None:
                    players[(crop.side, crop.row)].fields[crop.field_id] = result

        teams: list[TeamResult] = []
        warnings: list[str] = []
        for side in TeamSide:
            side_records = [
                players[(side, row)] for row in range(loaded.profile.row_relation.count)
            ]
            floryn_rows = [
                row
                for row, record in enumerate(side_records)
                if record.hero is not None
                and record.hero.status is ExtractionStatus.OK
                and record.hero.hero_id == FLORYN_ID
            ]
            seven_item_rows = [
                row for row, record in enumerate(side_records) if len(record.items) == 7
            ]
            if floryn_rows and len(seven_item_rows) != 1:
                warnings.append(
                    f"{side.value}.floryn_expected_one_seven_item_row_got_{len(seven_item_rows)}"
                )
            if seven_item_rows and not floryn_rows:
                warnings.append(f"{side.value}.seven_item_row_without_floryn_confirmation")
            for row in seven_item_rows:
                if not any(
                    item.status is ExtractionStatus.OK and item.item_id == FLOWER_OF_HOPE_ID
                    for item in side_records[row].items
                ):
                    warnings.append(
                        f"{side.value}.row{row}.seven_items_without_flower_of_hope_confirmation"
                    )
            player_results: list[PlayerResult] = []
            for row in range(loaded.profile.row_relation.count):
                record = players[(side, row)]
                sorted_items = tuple(sorted(record.items, key=lambda item: item.slot))
                player = PlayerResult(
                    row=row,
                    hero=record.hero,
                    items=sorted_items,
                    fields=record.fields,
                )
                player_results.append(player)
                if player.hero is not None and player.hero.status is not ExtractionStatus.OK:
                    warnings.append(f"{side.value}.row{row}.hero_abstained")
                warnings.extend(
                    f"{side.value}.row{row}.item{item.slot}_abstained"
                    for item in player.items
                    if item.status not in {ExtractionStatus.OK, ExtractionStatus.EMPTY}
                )
                warnings.extend(
                    f"{side.value}.row{row}.{field_id}_{extracted.status.value}"
                    for field_id, extracted in player.fields.items()
                    if extracted.status is not ExtractionStatus.OK
                )
            teams.append(TeamResult(side=side.value, players=tuple(player_results)))
        processing_ms = (perf_counter() - started) * 1000.0
        viewport = geometry.viewport.box if geometry.viewport else None
        return ExtractionResult(
            status=ExtractionStatus.OK,
            screen_type=geometry.screen.screen_type.value if geometry.screen.screen_type else None,
            provenance=Provenance(
                engine_version="2.0.0a0",
                catalog_version=self.catalog_version,
                ui_profile=geometry.profile_id,
                model_versions={
                    **self.visual_model_versions,
                    "ocr": ",".join(self.ocr_backend_names),
                    "ocr_pipeline": "semantic-ensemble-v3",
                    "ocr_selection_policy": self.ocr.selection_policy_version,
                },
                preprocessing_version="field-aware-crops-v2",
                processing_time_ms=processing_ms,
            ),
            source=SourceEvidence(
                original_resolution=Resolution(width=image.width, height=image.height),
                viewport=viewport,
                quality=QualityEvidence(
                    status=quality.status,
                    blur_score=quality.blur_score,
                    compression_score=quality.compression_quality_score,
                ),
                geometry=GeometryEvidence(
                    profile=geometry.profile_id,
                    confidence=geometry.screen.score,
                    confidence_semantics=ConfidenceSemantics.GEOMETRY,
                    hypotheses_attempted=len(geometry.anchors),
                ),
            ),
            metadata=metadata,
            teams=tuple(teams),
            warnings=tuple(sorted(set(warnings))),
        )

    def extract_with_artifacts(
        self,
        source: ImageSource,
        *,
        field_kinds: frozenset[FieldKind] | None = None,
    ) -> tuple[ExtractionResult, ExtractionArtifacts]:
        artifacts: list[ExtractionArtifacts] = []
        result = self.extract(source, field_kinds=field_kinds, _artifact_sink=artifacts.append)
        if len(artifacts) != 1:
            raise RuntimeError("extraction did not produce exactly one artifact bundle")
        return result, artifacts[0]

    def extract_match(self, sources: tuple[ImageSource, ...]) -> tuple[ExtractionResult, ...]:
        """Extract several tabs and reconcile only repeated OCR values with clear local support."""

        if not sources:
            raise ValueError("match extraction requires at least one screenshot")
        with self._match_inference_scope():
            results = tuple(self.extract(source) for source in sources)
        return self._reconcile_match_results(results)

    def extract_match_with_artifacts(
        self, sources: tuple[ImageSource, ...]
    ) -> tuple[tuple[ExtractionResult, ...], tuple[ExtractionArtifacts, ...]]:
        """Extract a match and retain the already-decoded geometry/crops for review tooling."""

        if not sources:
            raise ValueError("match extraction requires at least one screenshot")
        with self._match_inference_scope():
            extracted = tuple(self.extract_with_artifacts(source) for source in sources)
        results = tuple(result for result, _artifacts in extracted)
        artifacts = tuple(artifact for _result, artifact in extracted)
        return self._reconcile_match_results(results), artifacts

    def _reconcile_match_results(
        self, results: tuple[ExtractionResult, ...]
    ) -> tuple[ExtractionResult, ...]:
        observations: dict[str, list[ExtractedField]] = defaultdict(list)
        for result in results:
            for field_id, extracted in result.metadata.items():
                if extracted.status is ExtractionStatus.OK:
                    observations[f"metadata:{field_id}"].append(extracted)
            for team in result.teams:
                for player in team.players:
                    for field_id, extracted in player.fields.items():
                        if extracted.status is ExtractionStatus.OK:
                            key = f"player:{team.side}:{player.row}:{field_id}"
                            observations[key].append(extracted)

        consensus: dict[str, tuple[ExtractedField, int, int]] = {}
        for key, fields in observations.items():
            by_value: dict[str, list[ExtractedField]] = defaultdict(list)
            for extracted in fields:
                value_key = json.dumps(
                    {"type": type(extracted.value).__name__, "value": extracted.value},
                    sort_keys=True,
                    ensure_ascii=False,
                )
                by_value[value_key].append(extracted)
            ranked = sorted(
                by_value.values(),
                key=lambda members: (
                    -len(members),
                    -max(member.confidence or 0.0 for member in members),
                    json.dumps(members[0].value, ensure_ascii=False, sort_keys=True),
                ),
            )
            winner = ranked[0]
            if len(winner) < 2:
                continue
            best = max(winner, key=lambda field: field.confidence or 0.0)
            consensus[key] = (best, len(winner), len(fields))

        reconciled: list[ExtractionResult] = []
        for result in results:
            metadata = {
                field_id: self._apply_consensus(extracted, consensus.get(f"metadata:{field_id}"))
                for field_id, extracted in result.metadata.items()
            }
            teams: list[TeamResult] = []
            for team in result.teams:
                players: list[PlayerResult] = []
                for player in team.players:
                    reconciled_fields = {
                        field_id: self._apply_consensus(
                            extracted,
                            consensus.get(f"player:{team.side}:{player.row}:{field_id}"),
                        )
                        for field_id, extracted in player.fields.items()
                    }
                    players.append(player.model_copy(update={"fields": reconciled_fields}))
                teams.append(team.model_copy(update={"players": tuple(players)}))
            reconciled.append(
                result.model_copy(
                    update={
                        "metadata": metadata,
                        "teams": tuple(teams),
                        "warnings": tuple(
                            sorted(set((*result.warnings, "batch_consensus_applied")))
                        ),
                    }
                )
            )
        return tuple(reconciled)

    @staticmethod
    def _apply_consensus(
        original: ExtractedField,
        decision: tuple[ExtractedField, int, int] | None,
    ) -> ExtractedField:
        if decision is None:
            return original
        winner, support, total = decision
        return original.model_copy(
            update={
                "raw": winner.raw,
                "value": winner.value,
                "status": ExtractionStatus.OK,
                "confidence": winner.confidence,
                "confidence_semantics": winner.confidence_semantics,
                "candidates": tuple((*original.candidates, *winner.candidates))[:12],
                "validation_messages": tuple(
                    (*original.validation_messages, f"batch_consensus:{support}/{total}")
                ),
            }
        )

    def _early_result(
        self,
        *,
        status: ExtractionStatus,
        image_width: int,
        image_height: int,
        quality: ImageQuality,
        started: float,
        warning: str,
        viewport: tuple[int, int, int, int] | None = None,
    ) -> ExtractionResult:
        return ExtractionResult(
            status=status,
            provenance=Provenance(
                engine_version="2.0.0a0",
                catalog_version=self.catalog_version,
                model_versions=self.visual_model_versions,
                preprocessing_version="field-aware-crops-v2",
                processing_time_ms=(perf_counter() - started) * 1000.0,
            ),
            source=SourceEvidence(
                original_resolution=Resolution(width=image_width, height=image_height),
                viewport=viewport,
                quality=QualityEvidence(
                    status=status
                    if status is ExtractionStatus.LOW_QUALITY
                    else ExtractionStatus.OK,
                    blur_score=quality.blur_score,
                    compression_score=quality.compression_quality_score,
                ),
                geometry=GeometryEvidence(
                    failure_reason=warning or status.value,
                    hypotheses_attempted=0,
                ),
            ),
            warnings=(warning,) if warning else (),
        )


__all__ = ["ExtractionArtifacts", "NexusV2Engine"]
