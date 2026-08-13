from __future__ import annotations

import pytest

from nexus_v2.runtime import PerformanceProfile, parse_performance_profile, resolve_runtime_profile

CPU = ("CPUExecutionProvider",)
CPU_AND_CUDA = ("CUDAExecutionProvider", "CPUExecutionProvider")


def test_auto_selects_the_locally_certified_vectorized_cpu_profile() -> None:
    runtime = resolve_runtime_profile(PerformanceProfile.AUTO, available_providers=CPU_AND_CUDA)

    assert runtime.requested is PerformanceProfile.AUTO
    assert runtime.selected is PerformanceProfile.FAST_CPU_VECTORIZED
    assert runtime.execution_provider == "CPUExecutionProvider"
    assert runtime.rapidocr_text_detection is False
    assert runtime.hero_scoring_backend == "vectorized"
    assert runtime.vectorized_chunk_size == 256
    assert runtime.rapidocr_intra_op_num_threads == 1
    assert runtime.rapidocr_inter_op_num_threads == 1
    assert runtime.certification.selected_output_certified is True
    assert runtime.certification.complete_evidence_parity is False


def test_vectorized_profile_reports_completed_reviewed_certification() -> None:
    runtime = resolve_runtime_profile("fast-cpu-vectorized", available_providers=CPU)

    assert runtime.selected is PerformanceProfile.FAST_CPU_VECTORIZED
    assert runtime.execution_provider == "CPUExecutionProvider"
    assert runtime.rapidocr_text_detection is False
    assert runtime.hero_scoring_backend == "vectorized"
    assert runtime.vectorized_chunk_size == 256
    assert runtime.certification.selected_output_certified is True
    assert runtime.certification.reviewed_hero_exact == 4281
    assert runtime.certification.reviewed_hero_known == 4346
    assert runtime.certification.reviewed_item_exact == 320
    assert runtime.certification.reviewed_item_known == 324
    assert runtime.certification.reviewed_item_wrong == 1
    assert runtime.certification.reviewed_item_abstained == 3
    assert runtime.provenance_versions()["hero_scoring_backend"] == "vectorized"


def test_explicit_fast_cpu_remains_the_certified_scalar_rollback() -> None:
    runtime = resolve_runtime_profile("fast-cpu", available_providers=CPU)

    assert runtime.selected is PerformanceProfile.FAST_CPU
    assert runtime.hero_scoring_backend == "scalar"
    assert runtime.certification.selected_output_certified is True
    assert runtime.rapidocr_intra_op_num_threads == 1
    assert runtime.rapidocr_inter_op_num_threads == 1


def test_exact_cpu_retains_complete_evidence_parity_contract() -> None:
    runtime = resolve_runtime_profile("exact-cpu", available_providers=CPU)

    assert runtime.selected is PerformanceProfile.EXACT_CPU
    assert runtime.rapidocr_text_detection is True
    assert runtime.certification.complete_evidence_parity is True
    assert runtime.certification.reviewed_ocr_non_name_exact == 1848
    assert runtime.certification.reviewed_ocr_non_name_known == 1855
    assert runtime.certification.reviewed_hero_exact == 4281
    assert runtime.certification.reviewed_hero_known == 4346
    assert runtime.certification.reviewed_item_exact == 320
    assert runtime.certification.reviewed_item_known == 324
    assert runtime.certification.reviewed_item_wrong == 1
    assert runtime.certification.reviewed_item_abstained == 3


def test_cuda_profile_fails_closed_when_provider_is_unavailable() -> None:
    with pytest.raises(RuntimeError, match="CUDAExecutionProvider is unavailable"):
        resolve_runtime_profile("nvidia-cuda", available_providers=CPU)


def test_explicit_cuda_reports_that_hardware_certification_is_still_required() -> None:
    runtime = resolve_runtime_profile("nvidia-cuda", available_providers=CPU_AND_CUDA)

    assert runtime.execution_provider == "CUDAExecutionProvider"
    assert runtime.rapidocr_use_cuda is True
    assert runtime.certification.selected_output_certified is False


def test_invalid_profile_fails_closed() -> None:
    with pytest.raises(ValueError, match="unsupported performance profile"):
        parse_performance_profile("turbo-magic")
