"""Explicit, quality-gated runtime profiles for extraction inference."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final, Literal

import onnxruntime as ort  # type: ignore[import-untyped]


class PerformanceProfile(str, Enum):
    AUTO = "auto"
    EXACT_CPU = "exact-cpu"
    FAST_CPU = "fast-cpu"
    FAST_CPU_VECTORIZED = "fast-cpu-vectorized"
    NVIDIA_CUDA = "nvidia-cuda"


@dataclass(frozen=True)
class QualityCertification:
    certification_id: str
    selected_output_certified: bool
    complete_evidence_parity: bool
    reviewed_ocr_screenshots: int
    reviewed_ocr_non_name_exact: int
    reviewed_ocr_non_name_known: int
    reviewed_ocr_wrong: int
    reviewed_ocr_abstained: int
    reviewed_hero_exact: int
    reviewed_hero_known: int
    reviewed_hero_wrong: int
    reviewed_hero_abstained: int
    reviewed_item_exact: int
    reviewed_item_known: int
    reviewed_item_wrong: int
    reviewed_item_abstained: int

    def public_dict(self) -> dict[str, object]:
        return {
            "certification_id": self.certification_id,
            "selected_output_certified": self.selected_output_certified,
            "complete_evidence_parity": self.complete_evidence_parity,
            "reviewed_ocr_screenshots": self.reviewed_ocr_screenshots,
            "reviewed_ocr_non_name_exact": self.reviewed_ocr_non_name_exact,
            "reviewed_ocr_non_name_known": self.reviewed_ocr_non_name_known,
            "reviewed_ocr_wrong": self.reviewed_ocr_wrong,
            "reviewed_ocr_abstained": self.reviewed_ocr_abstained,
            "reviewed_hero_exact": self.reviewed_hero_exact,
            "reviewed_hero_known": self.reviewed_hero_known,
            "reviewed_hero_wrong": self.reviewed_hero_wrong,
            "reviewed_hero_abstained": self.reviewed_hero_abstained,
            "reviewed_item_exact": self.reviewed_item_exact,
            "reviewed_item_known": self.reviewed_item_known,
            "reviewed_item_wrong": self.reviewed_item_wrong,
            "reviewed_item_abstained": self.reviewed_item_abstained,
        }


_EXACT_CERTIFICATION: Final = QualityCertification(
    certification_id="reviewed-item-prototypes-cross-device-v1-exact-cpu",
    selected_output_certified=True,
    complete_evidence_parity=True,
    reviewed_ocr_screenshots=25,
    reviewed_ocr_non_name_exact=1848,
    reviewed_ocr_non_name_known=1855,
    reviewed_ocr_wrong=7,
    reviewed_ocr_abstained=0,
    reviewed_hero_exact=4281,
    reviewed_hero_known=4346,
    reviewed_hero_wrong=13,
    reviewed_hero_abstained=52,
    reviewed_item_exact=320,
    reviewed_item_known=324,
    reviewed_item_wrong=1,
    reviewed_item_abstained=3,
)

_FAST_CPU_CERTIFICATION: Final = QualityCertification(
    certification_id="reviewed-item-prototypes-cross-device-v1-fast-cpu",
    selected_output_certified=True,
    complete_evidence_parity=False,
    reviewed_ocr_screenshots=25,
    reviewed_ocr_non_name_exact=1848,
    reviewed_ocr_non_name_known=1855,
    reviewed_ocr_wrong=7,
    reviewed_ocr_abstained=0,
    reviewed_hero_exact=4281,
    reviewed_hero_known=4346,
    reviewed_hero_wrong=13,
    reviewed_hero_abstained=52,
    reviewed_item_exact=320,
    reviewed_item_known=324,
    reviewed_item_wrong=1,
    reviewed_item_abstained=3,
)

_UNCERTIFIED_CUDA: Final = QualityCertification(
    certification_id="nvidia-cuda-hardware-validation-required",
    selected_output_certified=False,
    complete_evidence_parity=False,
    reviewed_ocr_screenshots=0,
    reviewed_ocr_non_name_exact=0,
    reviewed_ocr_non_name_known=0,
    reviewed_ocr_wrong=0,
    reviewed_ocr_abstained=0,
    reviewed_hero_exact=0,
    reviewed_hero_known=0,
    reviewed_hero_wrong=0,
    reviewed_hero_abstained=0,
    reviewed_item_exact=0,
    reviewed_item_known=0,
    reviewed_item_wrong=0,
    reviewed_item_abstained=0,
)

_VECTORIZED_CERTIFICATION: Final = QualityCertification(
    certification_id="hero-vectorized-v2-item-prototypes-cross-device-v1",
    selected_output_certified=True,
    complete_evidence_parity=False,
    reviewed_ocr_screenshots=25,
    reviewed_ocr_non_name_exact=1848,
    reviewed_ocr_non_name_known=1855,
    reviewed_ocr_wrong=7,
    reviewed_ocr_abstained=0,
    reviewed_hero_exact=4281,
    reviewed_hero_known=4346,
    reviewed_hero_wrong=13,
    reviewed_hero_abstained=52,
    reviewed_item_exact=320,
    reviewed_item_known=324,
    reviewed_item_wrong=1,
    reviewed_item_abstained=3,
)


@dataclass(frozen=True)
class RuntimeProfile:
    requested: PerformanceProfile
    selected: PerformanceProfile
    execution_provider: str
    available_providers: tuple[str, ...]
    rapidocr_text_detection: bool
    rapidocr_use_cuda: bool
    rapidocr_intra_op_num_threads: int | None
    rapidocr_inter_op_num_threads: int | None
    hero_scoring_backend: Literal["scalar", "vectorized"]
    vectorized_chunk_size: int
    certification: QualityCertification

    def public_dict(self) -> dict[str, object]:
        return {
            "requested_profile": self.requested.value,
            "selected_profile": self.selected.value,
            "execution_provider": self.execution_provider,
            "available_providers": list(self.available_providers),
            "rapidocr_text_detection": self.rapidocr_text_detection,
            "rapidocr_intra_op_num_threads": self.rapidocr_intra_op_num_threads,
            "rapidocr_inter_op_num_threads": self.rapidocr_inter_op_num_threads,
            "hero_scoring_backend": self.hero_scoring_backend,
            "vectorized_chunk_size": self.vectorized_chunk_size,
            "certification": self.certification.public_dict(),
        }

    def provenance_versions(self) -> dict[str, str]:
        return {
            "performance_profile": self.selected.value,
            "onnx_execution_provider": self.execution_provider,
            "runtime_certification": self.certification.certification_id,
            "rapidocr_text_detection": str(self.rapidocr_text_detection).lower(),
            "rapidocr_intra_op_num_threads": str(self.rapidocr_intra_op_num_threads),
            "rapidocr_inter_op_num_threads": str(self.rapidocr_inter_op_num_threads),
            "hero_scoring_backend": self.hero_scoring_backend,
            "hero_vectorized_chunk_size": str(self.vectorized_chunk_size),
            "onnxruntime": ort.__version__,
        }


def parse_performance_profile(value: str | PerformanceProfile) -> PerformanceProfile:
    if isinstance(value, PerformanceProfile):
        return value
    try:
        return PerformanceProfile(value.strip().lower())
    except ValueError as exc:
        supported = ", ".join(profile.value for profile in PerformanceProfile)
        raise ValueError(
            f"unsupported performance profile {value!r}; choose one of: {supported}"
        ) from exc


def resolve_runtime_profile(
    requested: str | PerformanceProfile,
    *,
    available_providers: tuple[str, ...] | None = None,
) -> RuntimeProfile:
    parsed = parse_performance_profile(requested)
    providers = available_providers or tuple(ort.get_available_providers())
    if "CPUExecutionProvider" not in providers:
        raise RuntimeError("CPUExecutionProvider is required as the safe inference fallback")

    # Automatic selection is deliberately limited to hardware/profile combinations that have
    # completed the reviewed-corpus certification gate. CUDA remains explicit until its server is
    # benchmarked and certified.
    selected = (
        PerformanceProfile.FAST_CPU_VECTORIZED
        if parsed is PerformanceProfile.AUTO
        else parsed
    )
    if selected is PerformanceProfile.NVIDIA_CUDA:
        if "CUDAExecutionProvider" not in providers:
            available = ", ".join(providers)
            raise RuntimeError(
                "nvidia-cuda was requested, but CUDAExecutionProvider is unavailable; "
                f"available providers: {available}"
            )
        return RuntimeProfile(
            requested=parsed,
            selected=selected,
            execution_provider="CUDAExecutionProvider",
            available_providers=providers,
            rapidocr_text_detection=False,
            rapidocr_use_cuda=True,
            rapidocr_intra_op_num_threads=None,
            rapidocr_inter_op_num_threads=None,
            hero_scoring_backend="scalar",
            vectorized_chunk_size=128,
            certification=_UNCERTIFIED_CUDA,
        )
    if selected is PerformanceProfile.EXACT_CPU:
        return RuntimeProfile(
            requested=parsed,
            selected=selected,
            execution_provider="CPUExecutionProvider",
            available_providers=providers,
            rapidocr_text_detection=True,
            rapidocr_use_cuda=False,
            rapidocr_intra_op_num_threads=None,
            rapidocr_inter_op_num_threads=None,
            hero_scoring_backend="scalar",
            vectorized_chunk_size=128,
            certification=_EXACT_CERTIFICATION,
        )
    if selected is PerformanceProfile.FAST_CPU_VECTORIZED:
        return RuntimeProfile(
            requested=parsed,
            selected=selected,
            execution_provider="CPUExecutionProvider",
            available_providers=providers,
            rapidocr_text_detection=False,
            rapidocr_use_cuda=False,
            rapidocr_intra_op_num_threads=1,
            rapidocr_inter_op_num_threads=1,
            hero_scoring_backend="vectorized",
            vectorized_chunk_size=256,
            certification=_VECTORIZED_CERTIFICATION,
        )
    return RuntimeProfile(
        requested=parsed,
        selected=selected,
        execution_provider="CPUExecutionProvider",
        available_providers=providers,
        rapidocr_text_detection=False,
        rapidocr_use_cuda=False,
        rapidocr_intra_op_num_threads=1,
        rapidocr_inter_op_num_threads=1,
        hero_scoring_backend="scalar",
        vectorized_chunk_size=128,
        certification=_FAST_CPU_CERTIFICATION,
    )


__all__ = [
    "PerformanceProfile",
    "QualityCertification",
    "RuntimeProfile",
    "parse_performance_profile",
    "resolve_runtime_profile",
]
