"""Deterministic masked visual matching with stable-ID candidate evidence."""

from __future__ import annotations

import json
from copy import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import cv2
import numpy as np
from numpy.typing import NDArray

from nexus_v2.layout.cropper import SemanticCrop
from nexus_v2.layout.item_slots import item_occupancy
from nexus_v2.recognition.balanced import HeroBalancedPolicy
from nexus_v2.recognition.calibration import HeroAcceptancePolicy
from nexus_v2.recognition.reranker import HeroRerankerPolicy
from nexus_v2.schemas.result import (
    CandidateEvidence,
    ConfidenceSemantics,
    ExtractionStatus,
    HeroResult,
    ItemResult,
)

ImageArray = NDArray[np.uint8]
HeroScoringBackend = Literal["scalar", "vectorized"]


@dataclass(frozen=True)
class VisualMatcherConfig:
    size: int = 64
    minimum_score: float = 0.70
    minimum_margin: float = 0.018
    top_k: int = 5
    alignment_scales: tuple[float, ...] = (0.88, 0.94, 1.0, 1.06, 1.12)
    alignment_shifts: tuple[int, ...] = (-2, 0, 2)
    prototype_catalog_weight: float = 0.45
    item_prototype_catalog_weight: float = 0.0
    hero_preprocessing_views: tuple[str, ...] = ()
    hero_preprocessing_sides: tuple[str, ...] = ("ally", "enemy")
    preprocessing_bonus_weight: float = 0.0
    preprocessing_rerank_top_n: int = 5
    hero_acceptance_policy: HeroAcceptancePolicy | None = None
    hero_reranker_policy: HeroRerankerPolicy | None = None
    hero_balanced_policy: HeroBalancedPolicy | None = None
    hero_scoring_backend: HeroScoringBackend = "scalar"
    vectorized_chunk_size: int = 128
    vectorized_scalar_refine_top_n: int = 10

    def __post_init__(self) -> None:
        supported = {"clahe_luma", "gamma_085", "gamma_115", "unsharp"}
        unknown = set(self.hero_preprocessing_views) - supported
        if unknown:
            raise ValueError(f"unsupported hero preprocessing views: {sorted(unknown)}")
        unknown_sides = set(self.hero_preprocessing_sides) - {"ally", "enemy"}
        if unknown_sides:
            raise ValueError(f"unsupported hero preprocessing sides: {sorted(unknown_sides)}")
        if len(set(self.hero_preprocessing_sides)) != len(self.hero_preprocessing_sides):
            raise ValueError("hero preprocessing sides must be unique")
        if not 0.0 <= self.preprocessing_bonus_weight <= 1.0:
            raise ValueError("preprocessing bonus weight must be between zero and one")
        if self.preprocessing_rerank_top_n < 1:
            raise ValueError("preprocessing rerank top-n must be positive")
        if self.hero_balanced_policy is not None and (
            self.hero_acceptance_policy is not None or self.hero_reranker_policy is not None
        ):
            raise ValueError("balanced hero policy cannot be combined with legacy hero policies")
        if self.hero_scoring_backend not in {"scalar", "vectorized"}:
            raise ValueError("hero scoring backend must be scalar or vectorized")
        if self.vectorized_chunk_size < 1:
            raise ValueError("vectorized chunk size must be positive")
        if self.vectorized_scalar_refine_top_n < self.top_k:
            raise ValueError("vectorized scalar refinement must cover top_k")


@dataclass(frozen=True)
class VisualReference:
    entity_id: str | None
    name: str | None
    visual_id: str
    source: str
    image: ImageArray


@dataclass(frozen=True)
class _Features:
    rgb: NDArray[np.float32]
    gray: NDArray[np.float32]
    histogram: NDArray[np.float32]
    edge: ImageArray
    mask: NDArray[np.bool_]


@dataclass(frozen=True)
class _PreparedReference:
    reference: VisualReference
    features: _Features
    aligned_gray: NDArray[np.float32]


@dataclass(frozen=True)
class _VectorizedFeatureBank:
    """Contiguous reference features for exhaustive batched hero scoring."""

    aligned_gray: NDArray[np.float32]
    gray: NDArray[np.float32]
    gray_norm: NDArray[np.float64]
    color: NDArray[np.float32]
    color_norm: NDArray[np.float64]
    histogram: NDArray[np.float32]
    histogram_norm: NDArray[np.float64]
    edge: NDArray[np.float32]
    edge_norm: NDArray[np.float64]
    row_by_reference_identity: dict[int, int]


def _decode_rgb(path: Path) -> ImageArray:
    decoded = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if decoded is None:
        raise ValueError(f"unable to decode visual reference: {path}")
    if decoded.ndim == 2:
        return np.asarray(cv2.cvtColor(decoded, cv2.COLOR_GRAY2RGB), dtype=np.uint8)
    if decoded.shape[2] == 4:
        alpha = decoded[:, :, 3:4].astype(np.float32) / 255.0
        bgr = decoded[:, :, :3].astype(np.float32) * alpha
        decoded = np.asarray(np.clip(bgr, 0, 255), dtype=np.uint8)
    return np.asarray(cv2.cvtColor(decoded[:, :, :3], cv2.COLOR_BGR2RGB), dtype=np.uint8)


def _safe_relative(root: Path, relative: str) -> Path:
    resolved = (root / relative).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError("visual reference resolves outside its manifest root")
    if not resolved.is_file():
        raise ValueError(f"visual reference is missing: {resolved}")
    return resolved


def _prepare(image: ImageArray, size: int) -> _Features:
    height, width = image.shape[:2]
    margin_x = max(0, int(round(width * 0.055)))
    margin_y = max(0, int(round(height * 0.055)))
    cropped = image[margin_y : height - margin_y, margin_x : width - margin_x]
    resized = np.asarray(
        cv2.resize(cropped, (size, size), interpolation=cv2.INTER_AREA), dtype=np.uint8
    )
    rgb = resized.astype(np.float32) / 255.0
    gray = np.asarray(cv2.cvtColor(resized, cv2.COLOR_RGB2GRAY), dtype=np.float32) / 255.0
    yy, xx = np.ogrid[:size, :size]
    center = (size - 1) / 2.0
    mask = np.asarray((xx - center) ** 2 + (yy - center) ** 2 <= (size * 0.45) ** 2)
    hsv = cv2.cvtColor(resized, cv2.COLOR_RGB2HSV)
    histogram = np.asarray(
        cv2.calcHist(
            [hsv], [0, 1], mask.astype(np.uint8) * 255, [24, 16], [0, 180, 0, 256]
        ).reshape(-1),
        dtype=np.float32,
    )
    histogram_norm = float(np.linalg.norm(histogram))
    if histogram_norm > 1e-9:
        histogram = histogram / histogram_norm
    edge = np.asarray(cv2.Canny(resized, 35, 110), dtype=np.uint8)
    return _Features(rgb=rgb, gray=gray, histogram=histogram, edge=edge, mask=mask)


def _preprocess_view(image: ImageArray, name: str) -> ImageArray:
    """Return one mild deterministic query-only robustness view."""
    if name == "clahe_luma":
        lab = cv2.cvtColor(image, cv2.COLOR_RGB2LAB)
        lightness, first_chroma, second_chroma = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(4, 4))
        normalized = cv2.merge((clahe.apply(lightness), first_chroma, second_chroma))
        return np.asarray(cv2.cvtColor(normalized, cv2.COLOR_LAB2RGB), dtype=np.uint8)
    if name in {"gamma_085", "gamma_115"}:
        gamma = 0.85 if name == "gamma_085" else 1.15
        table = np.asarray(
            [round(255.0 * ((value / 255.0) ** gamma)) for value in range(256)],
            dtype=np.uint8,
        )
        return np.asarray(cv2.LUT(image, table), dtype=np.uint8)
    if name == "unsharp":
        blurred = cv2.GaussianBlur(image, (0, 0), 0.8)
        return np.asarray(cv2.addWeighted(image, 1.25, blurred, -0.25, 0.0), dtype=np.uint8)
    raise ValueError(f"unsupported hero preprocessing view: {name}")


def _correlation(left: NDArray[np.float32], right: NDArray[np.float32]) -> float:
    left_centered = left - float(left.mean())
    right_centered = right - float(right.mean())
    denominator = float(np.linalg.norm(left_centered) * np.linalg.norm(right_centered))
    if denominator <= 1e-9:
        return 0.0
    value = (float(np.dot(left_centered, right_centered)) / denominator + 1.0) / 2.0
    return float(np.clip(value, 0.0, 1.0))


def _standardized(values: NDArray[np.float32]) -> NDArray[np.float32]:
    centered = values - float(values.mean())
    norm = float(np.linalg.norm(centered))
    if norm <= 1e-9:
        return np.zeros_like(centered)
    return np.asarray(centered / norm, dtype=np.float32)


def _aligned_variants(features: _Features, config: VisualMatcherConfig) -> NDArray[np.float32]:
    size = config.size
    center = ((size - 1) / 2.0, (size - 1) / 2.0)
    variants: list[NDArray[np.float32]] = []
    for scale in config.alignment_scales:
        matrix = cv2.getRotationMatrix2D(center, 0.0, scale)
        scaled = np.asarray(
            cv2.warpAffine(
                features.gray,
                matrix,
                (size, size),
                flags=cv2.INTER_AREA,
                borderMode=cv2.BORDER_REPLICATE,
            ),
            dtype=np.float32,
        )
        for shift_x in config.alignment_shifts:
            for shift_y in config.alignment_shifts:
                moved = np.roll(scaled, (shift_y, shift_x), axis=(0, 1))
                variants.append(_standardized(moved[features.mask]))
    return np.vstack(variants).astype(np.float32)


def _similarity(
    query: _Features,
    reference: _Features,
    aligned_reference_gray: NDArray[np.float32],
) -> dict[str, float]:
    mask = query.mask & reference.mask
    gray = _correlation(query.gray[mask], reference.gray[mask])
    query_standardized = _standardized(query.gray[mask])
    aligned_gray = float(
        np.clip((float(np.max(aligned_reference_gray @ query_standardized)) + 1.0) / 2.0, 0.0, 1.0)
    )
    color_channels = [
        _correlation(query.rgb[:, :, channel][mask], reference.rgb[:, :, channel][mask])
        for channel in range(3)
    ]
    color = float(np.mean(color_channels))
    histogram = float(
        np.clip(
            (cv2.compareHist(query.histogram, reference.histogram, cv2.HISTCMP_CORREL) + 1.0) / 2.0,
            0.0,
            1.0,
        )
    )
    edge = _correlation(
        query.edge[mask].astype(np.float32) / 255.0,
        reference.edge[mask].astype(np.float32) / 255.0,
    )
    fused = 0.55 * aligned_gray + 0.20 * color + 0.20 * histogram + 0.05 * edge
    return {
        "fused_similarity": fused,
        "aligned_gray_correlation": aligned_gray,
        "gray_correlation": gray,
        "color_correlation": color,
        "histogram_correlation": histogram,
        "edge_correlation": edge,
    }


class ReferenceLibrary:
    def __init__(self, references: tuple[VisualReference, ...], *, kind: str) -> None:
        if kind not in {"hero", "item"}:
            raise ValueError("reference kind must be hero or item")
        if not references:
            raise ValueError("reference library cannot be empty")
        self.kind = kind
        self.references = references

    @classmethod
    def load(
        cls,
        catalog_path: Path,
        *,
        kind: str,
        prototype_manifest: Path | None = None,
    ) -> ReferenceLibrary:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        key = "heroes" if kind == "hero" else "items"
        catalog_ids = {str(entity["id"]) for entity in catalog[key]}
        references: list[VisualReference] = []
        for entity in catalog[key]:
            if kind == "item" and not entity.get("classification_enabled", False):
                continue
            for visual in entity["visual_versions"]:
                path = _safe_relative(catalog_path.parent, visual["asset_path"])
                references.append(
                    VisualReference(
                        entity_id=str(entity["id"]),
                        name=str(entity["canonical_name"]),
                        visual_id=str(visual["id"]),
                        source="catalog",
                        image=_decode_rgb(path),
                    )
                )
        if prototype_manifest is not None:
            payload = json.loads(prototype_manifest.read_text(encoding="utf-8"))
            if payload.get("kind") != kind:
                raise ValueError("prototype manifest kind mismatch")
            for record in payload["references"]:
                entity_id = record.get("entity_id")
                if entity_id is None and kind == "hero":
                    raise ValueError("hero prototype cannot represent an empty slot")
                if entity_id is not None and str(entity_id) not in catalog_ids:
                    raise ValueError("prototype entity ID is absent from the active catalog")
                path = _safe_relative(prototype_manifest.parent, record["asset_path"])
                references.append(
                    VisualReference(
                        entity_id=None if entity_id is None else str(entity_id),
                        name=record.get("name"),
                        visual_id=str(record["visual_id"]),
                        source="profile_prototype",
                        image=_decode_rgb(path),
                    )
                )
        return cls(tuple(references), kind=kind)


class VisualMatcher:
    def __init__(
        self,
        library: ReferenceLibrary,
        config: VisualMatcherConfig | None = None,
    ) -> None:
        self.library = library
        self.config = config or VisualMatcherConfig()
        if self.config.hero_scoring_backend == "vectorized" and library.kind != "hero":
            raise ValueError("vectorized scoring is currently certified for hero libraries only")
        self._vectorized_bank: _VectorizedFeatureBank | None = None
        if self.config.hero_scoring_backend == "vectorized":
            self._vectorized_bank, prepared = self._build_vectorized_bank(
                library.references, self.config
            )
        else:
            prepared = [
                _PreparedReference(
                    reference=reference,
                    features=(features := _prepare(reference.image, self.config.size)),
                    aligned_gray=_aligned_variants(features, self.config),
                )
                for reference in library.references
            ]
        self._features = tuple(prepared)

    def with_excluded_visual_ids(self, excluded_visual_ids: frozenset[str]) -> VisualMatcher:
        """Return an immutable scoring view that excludes exact reference visual IDs."""

        filtered = tuple(
            prepared
            for prepared in self._features
            if prepared.reference.visual_id not in excluded_visual_ids
        )
        if not filtered:
            raise ValueError("reference exclusion cannot remove every visual reference")
        matcher = copy(self)
        matcher._features = filtered
        return matcher

    @staticmethod
    def _build_vectorized_bank(
        references: tuple[VisualReference, ...],
        config: VisualMatcherConfig,
    ) -> tuple[_VectorizedFeatureBank, list[_PreparedReference]]:
        """Build each reference directly into its final contiguous bank allocation."""
        reference_count = len(references)
        first_features = _prepare(references[0].image, config.size)
        first_aligned = _aligned_variants(first_features, config)
        variant_count, pixel_count = first_aligned.shape
        aligned_gray = np.empty((reference_count, variant_count, pixel_count), dtype=np.float32)
        gray = np.empty((reference_count, pixel_count), dtype=np.float32)
        gray_norm = np.empty(reference_count, dtype=np.float64)
        color = np.empty((reference_count, 3, pixel_count), dtype=np.float32)
        color_norm = np.empty((reference_count, 3), dtype=np.float64)
        histogram = np.empty((reference_count, first_features.histogram.size), dtype=np.float32)
        histogram_norm = np.empty(reference_count, dtype=np.float64)
        edge = np.empty((reference_count, pixel_count), dtype=np.float32)
        edge_norm = np.empty(reference_count, dtype=np.float64)
        rebuilt: list[_PreparedReference] = []
        row_by_reference_identity: dict[int, int] = {}
        for index, reference in enumerate(references):
            features = first_features if index == 0 else _prepare(reference.image, config.size)
            reference_aligned = first_aligned if index == 0 else _aligned_variants(features, config)
            mask = features.mask
            aligned_gray[index] = reference_aligned
            gray_values = features.gray[mask]
            gray[index] = gray_values - float(gray_values.mean())
            gray_norm[index] = float(np.linalg.norm(gray[index]))
            for channel in range(3):
                color_values = features.rgb[:, :, channel][mask]
                color[index, channel] = color_values - float(color_values.mean())
                color_norm[index, channel] = float(np.linalg.norm(color[index, channel]))
            histogram[index] = features.histogram - float(features.histogram.mean())
            histogram_norm[index] = float(np.linalg.norm(histogram[index]))
            edge_values = features.edge[mask].astype(np.float32) / 255.0
            edge[index] = edge_values - float(edge_values.mean())
            edge_norm[index] = float(np.linalg.norm(edge[index]))
            row_by_reference_identity[id(reference)] = index
            rebuilt.append(
                _PreparedReference(
                    reference=reference,
                    features=features,
                    aligned_gray=aligned_gray[index],
                )
            )
        return (
            _VectorizedFeatureBank(
                aligned_gray=aligned_gray,
                gray=gray,
                gray_norm=gray_norm,
                color=color,
                color_norm=color_norm,
                histogram=histogram,
                histogram_norm=histogram_norm,
                edge=edge,
                edge_norm=edge_norm,
                row_by_reference_identity=row_by_reference_identity,
            ),
            rebuilt,
        )

    def _vectorized_scores(
        self,
        query: _Features,
        rows: NDArray[np.intp],
    ) -> dict[str, NDArray[np.float64]]:
        bank = self._vectorized_bank
        if bank is None:
            raise RuntimeError("vectorized hero feature bank is unavailable")
        mask = query.mask
        query_gray_values = query.gray[mask]
        query_gray_centered = query_gray_values - float(query_gray_values.mean())
        query_gray_norm = float(np.linalg.norm(query_gray_centered))
        query_gray = _standardized(query_gray_values)
        query_color = np.empty((3, query_gray.size), dtype=np.float32)
        query_color_norm = np.empty(3, dtype=np.float64)
        for channel in range(3):
            values = query.rgb[:, :, channel][mask]
            query_color[channel] = values - float(values.mean())
            query_color_norm[channel] = float(np.linalg.norm(query_color[channel]))
        query_histogram = query.histogram - float(query.histogram.mean())
        query_histogram_norm = float(np.linalg.norm(query_histogram))
        query_edge_values = query.edge[mask].astype(np.float32) / 255.0
        query_edge = query_edge_values - float(query_edge_values.mean())
        query_edge_norm = float(np.linalg.norm(query_edge))
        count = len(rows)
        aligned = np.empty(count, dtype=np.float64)
        gray = np.empty(count, dtype=np.float64)
        color = np.empty(count, dtype=np.float64)
        histogram = np.empty(count, dtype=np.float64)
        edge = np.empty(count, dtype=np.float64)
        chunk_size = self.config.vectorized_chunk_size
        for start in range(0, count, chunk_size):
            stop = min(start + chunk_size, count)
            selected = rows[start:stop]
            contiguous = len(selected) == 1 or bool(np.all(np.diff(selected) == 1))
            bank_rows: slice | NDArray[np.intp] = (
                slice(int(selected[0]), int(selected[-1]) + 1) if contiguous else selected
            )
            aligned_dot = np.matmul(bank.aligned_gray[bank_rows], query_gray)
            aligned[start:stop] = np.max(aligned_dot, axis=1)
            gray_denominator = bank.gray_norm[bank_rows] * query_gray_norm
            gray_raw = np.divide(
                np.matmul(bank.gray[bank_rows], query_gray_centered),
                gray_denominator,
                out=np.zeros(stop - start, dtype=np.float64),
                where=gray_denominator > 1e-9,
            )
            gray[start:stop] = np.where(
                gray_denominator > 1e-9,
                np.clip((gray_raw + 1.0) / 2.0, 0.0, 1.0),
                0.0,
            )
            color_denominator = bank.color_norm[bank_rows] * query_color_norm[None, :]
            color_raw = np.divide(
                np.sum(bank.color[bank_rows] * query_color[None, :, :], axis=2),
                color_denominator,
                out=np.zeros((stop - start, 3), dtype=np.float64),
                where=color_denominator > 1e-9,
            )
            color[start:stop] = np.mean(
                np.where(
                    color_denominator > 1e-9,
                    np.clip((color_raw + 1.0) / 2.0, 0.0, 1.0),
                    0.0,
                ),
                axis=1,
            )
            histogram_denominator = bank.histogram_norm[bank_rows] * query_histogram_norm
            histogram_raw = np.divide(
                np.matmul(bank.histogram[bank_rows], query_histogram),
                histogram_denominator,
                out=np.zeros(stop - start, dtype=np.float64),
                where=histogram_denominator > 1e-9,
            )
            histogram[start:stop] = np.where(
                histogram_denominator > 1e-9,
                np.clip((histogram_raw + 1.0) / 2.0, 0.0, 1.0),
                1.0,
            )
            edge_denominator = bank.edge_norm[bank_rows] * query_edge_norm
            edge_raw = np.divide(
                np.matmul(bank.edge[bank_rows], query_edge),
                edge_denominator,
                out=np.zeros(stop - start, dtype=np.float64),
                where=edge_denominator > 1e-9,
            )
            edge[start:stop] = np.where(
                edge_denominator > 1e-9,
                np.clip((edge_raw + 1.0) / 2.0, 0.0, 1.0),
                0.0,
            )

        # Correlations use the same [-1, 1] to [0, 1] transform as the scalar path.
        aligned_correlation = np.asarray(np.clip((aligned + 1.0) / 2.0, 0.0, 1.0), dtype=np.float64)
        fused = 0.55 * aligned_correlation + 0.20 * color + 0.20 * histogram + 0.05 * edge
        return {
            "fused_similarity": fused,
            "aligned_gray_correlation": aligned_correlation,
            "gray_correlation": gray,
            "color_correlation": color,
            "histogram_correlation": histogram,
            "edge_correlation": edge,
        }

    def _score_entities_vectorized(
        self,
        queries: tuple[_Features, ...],
        *,
        allowed_entities: frozenset[str] | None,
    ) -> dict[str, dict[str, tuple[VisualReference, dict[str, float]]]]:
        bank = self._vectorized_bank
        if bank is None:
            raise RuntimeError("vectorized hero feature bank is unavailable")
        active = [
            prepared
            for prepared in self._features
            if allowed_entities is None
            or (prepared.reference.entity_id or "__empty__") in allowed_entities
        ]
        rows = np.asarray(
            [bank.row_by_reference_identity[id(prepared.reference)] for prepared in active],
            dtype=np.intp,
        )
        query_scores = [self._vectorized_scores(query, rows) for query in queries]
        by_entity: dict[str, dict[str, tuple[VisualReference, dict[str, float]]]] = {}
        for local_index, prepared in enumerate(active):
            reference = prepared.reference
            key = reference.entity_id or "__empty__"
            selected_index = max(
                range(len(query_scores)),
                key=lambda index: (
                    float(query_scores[index]["fused_similarity"][local_index]),
                    -index,
                ),
            )
            scores = {
                name: float(values[local_index])
                for name, values in query_scores[selected_index].items()
            }
            if len(queries) > 1:
                scores["query_view_index"] = float(selected_index)
            by_source = by_entity.setdefault(key, {})
            previous = by_source.get(reference.source)
            if previous is None or scores["fused_similarity"] > previous[1]["fused_similarity"]:
                by_source[reference.source] = (reference, scores)
        return by_entity

    def _score_entities_scalar(
        self,
        queries: tuple[_Features, ...],
        *,
        allowed_entities: frozenset[str] | None = None,
    ) -> dict[str, dict[str, tuple[VisualReference, dict[str, float]]]]:
        by_entity: dict[str, dict[str, tuple[VisualReference, dict[str, float]]]] = {}
        for prepared in self._features:
            reference = prepared.reference
            key = reference.entity_id or "__empty__"
            if allowed_entities is not None and key not in allowed_entities:
                continue
            scored_views = [
                _similarity(query, prepared.features, prepared.aligned_gray) for query in queries
            ]
            selected_index, scores = max(
                enumerate(scored_views),
                key=lambda item: (item[1]["fused_similarity"], -item[0]),
            )
            scores = dict(scores)
            if len(queries) > 1:
                scores["query_view_index"] = float(selected_index)
            by_source = by_entity.setdefault(key, {})
            previous = by_source.get(reference.source)
            if previous is None or scores["fused_similarity"] > previous[1]["fused_similarity"]:
                by_source[reference.source] = (reference, scores)
        return by_entity

    def _fuse_entities(
        self,
        by_entity: dict[str, dict[str, tuple[VisualReference, dict[str, float]]]],
    ) -> list[tuple[VisualReference, dict[str, float]]]:
        fused_entities: list[tuple[VisualReference, dict[str, float]]] = []
        for by_source in by_entity.values():
            catalog = by_source.get("catalog")
            prototype = by_source.get("profile_prototype")
            if catalog is None or prototype is None:
                fused_entities.append(prototype or catalog or next(iter(by_source.values())))
                continue
            prototype_reference, prototype_scores = prototype
            _, catalog_scores = catalog
            scores = dict(prototype_scores)
            scores["prototype_similarity"] = prototype_scores["fused_similarity"]
            scores["catalog_similarity"] = catalog_scores["fused_similarity"]
            if "query_view_index" in catalog_scores:
                scores["catalog_query_view_index"] = catalog_scores["query_view_index"]
            weight = (
                self.config.item_prototype_catalog_weight
                if self.library.kind == "item"
                else self.config.prototype_catalog_weight
            )
            scores["fused_similarity"] = (1.0 - weight) * prototype_scores[
                "fused_similarity"
            ] + weight * catalog_scores["fused_similarity"]
            fused_entities.append((prototype_reference, scores))
        return fused_entities

    def _score_entities(
        self,
        queries: tuple[_Features, ...],
        *,
        allowed_entities: frozenset[str] | None = None,
    ) -> dict[str, dict[str, tuple[VisualReference, dict[str, float]]]]:
        if self.config.hero_scoring_backend == "scalar":
            return self._score_entities_scalar(queries, allowed_entities=allowed_entities)
        approximate = self._score_entities_vectorized(queries, allowed_entities=allowed_entities)
        fused = sorted(
            self._fuse_entities(approximate),
            key=lambda item: (-item[1]["fused_similarity"], item[0].visual_id),
        )
        balanced_top_n = (
            self.config.hero_balanced_policy.top_n
            if self.config.hero_balanced_policy is not None
            else 0
        )
        refinement_floor = max(
            self.config.vectorized_scalar_refine_top_n,
            self.config.top_k,
            self.config.preprocessing_rerank_top_n,
            balanced_top_n,
        )
        cutoff_index = min(refinement_floor, len(fused)) - 1
        cutoff = fused[cutoff_index][1]["fused_similarity"]
        refinement_entities = frozenset(
            reference.entity_id or "__empty__"
            for reference, scores in fused
            if scores["fused_similarity"] >= cutoff - 1e-5
        )
        exact = self._score_entities_scalar(queries, allowed_entities=refinement_entities)
        approximate.update(exact)
        return approximate

    def _rank(self, crop: SemanticCrop) -> list[tuple[VisualReference, dict[str, float]]]:
        query = _prepare(crop.tight_rgb, self.config.size)
        originals = self._fuse_entities(self._score_entities((query,)))
        ranked_originals = sorted(
            originals,
            key=lambda item: (-item[1]["fused_similarity"], item[0].visual_id),
        )
        if (
            crop.kind.value != "hero"
            or not self.config.hero_preprocessing_views
            or self.config.preprocessing_bonus_weight <= 0.0
            or crop.side is None
            or crop.side.value not in self.config.hero_preprocessing_sides
        ):
            return self._rerank_hero(ranked_originals, crop)

        target_entities = frozenset(
            reference.entity_id or "__empty__"
            for reference, _ in ranked_originals[: self.config.preprocessing_rerank_top_n]
        )
        query_views = (
            query,
            *(
                _prepare(_preprocess_view(crop.tight_rgb, name), self.config.size)
                for name in self.config.hero_preprocessing_views
            ),
        )
        enhanced = {
            reference.entity_id or "__empty__": (reference, scores)
            for reference, scores in self._fuse_entities(
                self._score_entities(query_views, allowed_entities=target_entities)
            )
        }
        adjusted: list[tuple[VisualReference, dict[str, float]]] = []
        for original_reference, original_scores in ranked_originals:
            key = original_reference.entity_id or "__empty__"
            candidate = enhanced.get(key)
            if candidate is None:
                adjusted.append((original_reference, original_scores))
                continue
            enhanced_reference, enhanced_scores = candidate
            original_similarity = original_scores["fused_similarity"]
            enhanced_similarity = enhanced_scores["fused_similarity"]
            gain = max(0.0, enhanced_similarity - original_similarity)
            scores = dict(enhanced_scores)
            scores["original_similarity"] = original_similarity
            scores["preprocessing_similarity"] = enhanced_similarity
            scores["preprocessing_gain"] = gain
            scores["fused_similarity"] = (
                original_similarity + self.config.preprocessing_bonus_weight * gain
            )
            adjusted.append((enhanced_reference, scores))
        return self._rerank_hero(
            sorted(
                adjusted,
                key=lambda item: (-item[1]["fused_similarity"], item[0].visual_id),
            ),
            crop,
        )

    def _rerank_hero(
        self,
        ranked: list[tuple[VisualReference, dict[str, float]]],
        crop: SemanticCrop,
    ) -> list[tuple[VisualReference, dict[str, float]]]:
        policy = self.config.hero_reranker_policy
        balanced = self.config.hero_balanced_policy
        if crop.kind.value != "hero" or (policy is None and balanced is None):
            return ranked
        champion_margin = (
            ranked[0][1]["fused_similarity"] - ranked[1][1]["fused_similarity"]
            if len(ranked) > 1
            else 1.0
        )
        champion_abstained = (
            ranked[0][1]["fused_similarity"] < self.config.minimum_score
            or champion_margin < self.config.minimum_margin
        )
        if balanced is not None:
            if balanced.only_abstained and not champion_abstained:
                return ranked
            if len(ranked) < balanced.top_n or not all(
                balanced.supports(scores) for _, scores in ranked[: balanced.top_n]
            ):
                return ranked
            head = [
                (
                    reference,
                    {
                        **scores,
                        "balanced_policy_score": balanced.score(scores),
                        "balanced_policy_eligible": 1.0,
                    },
                )
                for reference, scores in ranked[: balanced.top_n]
            ]
            reordered = sorted(
                head,
                key=lambda item: (-item[1]["balanced_policy_score"], item[0].visual_id),
            )
            if reordered[0][0].entity_id != ranked[0][0].entity_id:
                reordered[0][1]["balanced_policy_override"] = 1.0
            reordered[0][1]["balanced_policy_margin"] = (
                reordered[0][1]["balanced_policy_score"] - reordered[1][1]["balanced_policy_score"]
            )
            return [*reordered, *ranked[balanced.top_n :]]
        assert policy is not None
        if policy.only_abstained and not champion_abstained:
            return ranked
        head = [
            (reference, {**scores, "reranker_score": policy.score(scores)})
            for reference, scores in ranked[: policy.top_n]
        ]
        challenger_index = max(
            range(len(head)),
            key=lambda index: (head[index][1]["reranker_score"], -index),
        )
        challenger_lead = head[challenger_index][1]["reranker_score"] - head[0][1]["reranker_score"]
        if challenger_index == 0 or challenger_lead < policy.override_lead:
            return ranked
        reordered = sorted(
            head,
            key=lambda item: (-item[1]["reranker_score"], item[0].visual_id),
        )
        reordered[0][1]["reranker_override"] = 1.0
        reordered[0][1]["reranker_margin"] = (
            reordered[0][1]["reranker_score"] - reordered[1][1]["reranker_score"]
        )
        return [*reordered, *ranked[policy.top_n :]]

    def _evidence(
        self, ranked: list[tuple[VisualReference, dict[str, float]]]
    ) -> tuple[CandidateEvidence, ...]:
        result: list[CandidateEvidence] = []
        for index, (reference, scores) in enumerate(ranked[: self.config.top_k]):
            expanded = dict(scores)
            if index + 1 < len(ranked):
                score_key = (
                    "balanced_policy_score"
                    if "balanced_policy_score" in scores
                    else "reranker_score"
                    if "reranker_score" in scores
                    else "fused_similarity"
                )
                expanded["margin_to_next"] = max(
                    0.0,
                    scores[score_key] - ranked[index + 1][1].get(score_key, 0.0),
                )
            result.append(
                CandidateEvidence(
                    candidate_id=reference.entity_id,
                    label=reference.name,
                    scores=expanded,
                )
            )
        return tuple(result)

    def match_hero(self, crop: SemanticCrop) -> HeroResult:
        if self.library.kind != "hero":
            raise ValueError("hero matching requires a hero reference library")
        ranked = self._rank(crop)
        best_reference, best_scores = ranked[0]
        margin = (
            best_scores.get(
                "balanced_policy_margin",
                best_scores.get(
                    "reranker_margin",
                    best_scores["fused_similarity"] - ranked[1][1]["fused_similarity"],
                ),
            )
            if len(ranked) > 1
            else 1.0
        )
        balanced = self.config.hero_balanced_policy
        balanced_eligible = best_scores.get("balanced_policy_eligible") == 1.0
        policy = self.config.hero_acceptance_policy
        minimum_score = policy.minimum_score if policy is not None else self.config.minimum_score
        minimum_margin = self.config.minimum_margin
        if balanced is not None and balanced_eligible and len(ranked) > 1:
            runner_scores = ranked[1][1]
            accepted = best_reference.entity_id is not None and balanced.accepts(
                best_scores,
                runner_scores,
                rank_margin=margin,
            )
            best_scores["balanced_policy_minimum_prototype"] = balanced.minimum_prototype
            best_scores["balanced_policy_minimum_rank_margin"] = balanced.minimum_rank_margin
            best_scores["balanced_policy_minimum_prototype_margin"] = (
                balanced.minimum_prototype_margin
            )
            best_scores["balanced_policy_minimum_votes"] = float(balanced.minimum_votes)
            best_scores["balanced_policy_channel_votes"] = float(
                balanced.channel_votes(best_scores, runner_scores)
            )
        else:
            if (
                policy is not None
                and crop.side is not None
                and best_reference.entity_id is not None
            ):
                minimum_margin = policy.minimum_margin(
                    side=crop.side.value, hero_id=best_reference.entity_id
                )
                best_scores["acceptance_minimum_score"] = minimum_score
                best_scores["acceptance_minimum_margin"] = minimum_margin
            accepted = (
                best_reference.entity_id is not None
                and best_scores["fused_similarity"] >= minimum_score
                and margin >= minimum_margin
            )
        return HeroResult(
            hero_id=best_reference.entity_id if accepted else None,
            name=best_reference.name if accepted else None,
            status=ExtractionStatus.OK if accepted else ExtractionStatus.UNKNOWN,
            confidence=best_scores["fused_similarity"],
            confidence_semantics=ConfidenceSemantics.TEMPLATE_SIMILARITY,
            source_box=crop.tight_box,
            candidates=self._evidence(ranked),
        )

    def match_item(self, crop: SemanticCrop) -> ItemResult:
        if self.library.kind != "item":
            raise ValueError("item matching requires an item reference library")
        if crop.slot is None:
            raise ValueError("item crop must declare its slot index")
        if crop.clipped or crop.tight_rgb.size == 0:
            return ItemResult(
                slot=crop.slot,
                status=ExtractionStatus.INVALID_CROP,
                source_box=crop.tight_box,
            )
        occupancy, occupancy_scores = item_occupancy(crop.tight_rgb)
        occupancy_evidence = CandidateEvidence(
            candidate_id=None,
            label=(
                "EMPTY"
                if occupancy is ExtractionStatus.EMPTY
                else "OCCUPIED"
                if occupancy is ExtractionStatus.OCCUPIED
                else "OCCUPANCY_UNCERTAIN"
            ),
            scores=occupancy_scores,
        )
        if occupancy is ExtractionStatus.EMPTY:
            return ItemResult(
                slot=crop.slot,
                status=ExtractionStatus.EMPTY,
                source_box=crop.tight_box,
                candidates=(occupancy_evidence,),
            )
        ranked = [candidate for candidate in self._rank(crop) if candidate[0].entity_id is not None]
        best_reference, best_scores = ranked[0]
        margin = (
            best_scores["fused_similarity"] - ranked[1][1]["fused_similarity"]
            if len(ranked) > 1
            else 1.0
        )
        accepted = (
            best_scores["fused_similarity"] >= self.config.minimum_score
            and margin >= self.config.minimum_margin
        )
        if accepted:
            status = ExtractionStatus.OK
            item_id = best_reference.entity_id
            name = best_reference.name
        else:
            status = ExtractionStatus.UNKNOWN
            item_id = None
            name = None
        return ItemResult(
            slot=crop.slot,
            item_id=item_id,
            name=name,
            status=status,
            confidence=best_scores["fused_similarity"],
            confidence_semantics=ConfidenceSemantics.TEMPLATE_SIMILARITY,
            source_box=crop.tight_box,
            candidates=(occupancy_evidence, *self._evidence(ranked)),
        )


__all__ = [
    "ReferenceLibrary",
    "VisualMatcher",
    "VisualMatcherConfig",
    "VisualReference",
]
