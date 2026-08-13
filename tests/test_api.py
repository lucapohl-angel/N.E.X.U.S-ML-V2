from __future__ import annotations

import threading
import time
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from nexus_v2.api.app import APISettings, create_app
from nexus_v2.api.jobs import JobStatus, MatchJobService
from nexus_v2.recognition import VisualMatcherConfig
from nexus_v2.runtime import resolve_runtime_profile
from nexus_v2.schemas.result import (
    ExtractedField,
    ExtractionResult,
    ExtractionStatus,
    GeometryEvidence,
    Provenance,
    QualityEvidence,
    Resolution,
    SourceEvidence,
)

ROLES = ("hero_item", "overall", "dps", "farm", "team")


def _result() -> ExtractionResult:
    return ExtractionResult(
        status=ExtractionStatus.OK,
        screen_type="test",
        provenance=Provenance(
            engine_version="test",
            preprocessing_version="test",
            processing_time_ms=1.0,
        ),
        source=SourceEvidence(
            original_resolution=Resolution(width=1, height=1),
            quality=QualityEvidence(status=ExtractionStatus.OK),
            geometry=GeometryEvidence(),
        ),
    )


class FakeEngine:
    def __init__(self, *, release: threading.Event | None = None, delay: float = 0.0) -> None:
        self.release = release
        self.delay = delay
        self.started = threading.Event()
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.calls = 0

    def extract_match(self, sources: tuple[bytes, ...]) -> tuple[ExtractionResult, ...]:
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.calls += 1
            self.started.set()
        try:
            if self.release is not None and not self.release.wait(timeout=3):
                raise TimeoutError("test release was not signaled")
            if self.delay:
                time.sleep(self.delay)
            return tuple(_result() for _ in sources)
        finally:
            with self._lock:
                self.active -= 1


def _wait_for(
    service: MatchJobService,
    job_id: str,
    status: JobStatus,
    *,
    timeout: float = 3.0,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if service.get(job_id).status is status:
            return
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not reach {status.value}")


def _payload(seed: bytes = b"same") -> tuple[bytes, ...]:
    return tuple(seed + str(index).encode("ascii") for index in range(5))


def test_service_preloads_once_deduplicates_only_active_jobs_and_releases_sources() -> None:
    release = threading.Event()
    engine = FakeEngine(release=release)
    builds = 0

    def factory() -> FakeEngine:
        nonlocal builds
        builds += 1
        return engine

    service = MatchJobService(factory)
    service.start()
    try:
        assert builds == 1
        first = service.submit(_payload())
        assert engine.started.wait(timeout=1)
        duplicate = service.submit(_payload())
        assert duplicate.job_id == first.job_id
        assert duplicate.deduplicated is True
        assert engine.calls == 1

        release.set()
        _wait_for(service, first.job_id, JobStatus.COMPLETED)
        completed = service.get(first.job_id)
        assert completed.source_bytes_retained == 0
        assert completed.result is not None

        repeated = service.submit(_payload())
        assert repeated.job_id != first.job_id
        assert repeated.deduplicated is False
        _wait_for(service, repeated.job_id, JobStatus.COMPLETED)
        assert engine.calls == 2
        service.start()
        assert builds == 1
    finally:
        service.stop()


def test_service_runs_distinct_jobs_one_at_a_time() -> None:
    engine = FakeEngine(delay=0.03)
    service = MatchJobService(lambda: engine)
    service.start()
    try:
        first = service.submit(_payload(b"first"))
        second = service.submit(_payload(b"second"))
        _wait_for(service, first.job_id, JobStatus.COMPLETED)
        _wait_for(service, second.job_id, JobStatus.COMPLETED)
        assert engine.calls == 2
        assert engine.max_active == 1
        health = service.health()
        assert health["max_parallel_jobs"] == 1
        assert health["engine_loaded"] is True
    finally:
        service.stop()


def _files(seed: bytes = b"image") -> dict[str, tuple[str, bytes, str]]:
    return {role: (f"{role}.jpg", seed + role.encode("ascii"), "image/jpeg") for role in ROLES}


def test_http_api_submits_polls_returns_results_and_deduplicates_active_uploads() -> None:
    release = threading.Event()
    engine = FakeEngine(release=release)
    service = MatchJobService(lambda: engine)
    app = create_app(service=service)

    with TestClient(app) as client:
        health = client.get("/v2/health")
        assert health.status_code == 200
        assert health.json()["max_parallel_jobs"] == 1
        assert health.json()["engine_loaded"] is True

        first = client.post("/v2/extract-match", files=_files())
        assert first.status_code == 202
        first_payload = first.json()
        assert first_payload["deduplicated"] is False
        assert engine.started.wait(timeout=1)

        duplicate = client.post("/v2/extract-match", files=_files())
        assert duplicate.status_code == 202
        assert duplicate.json()["job_id"] == first_payload["job_id"]
        assert duplicate.json()["deduplicated"] is True

        status = client.get(f"/v2/jobs/{first_payload['job_id']}")
        assert status.status_code == 200
        assert status.json()["status"] in {"queued", "processing"}

        pending = client.get(f"/v2/jobs/{first_payload['job_id']}/result")
        assert pending.status_code == 202

        release.set()
        _wait_for(service, first_payload["job_id"], JobStatus.COMPLETED)
        completed = client.get(f"/v2/jobs/{first_payload['job_id']}/result")
        assert completed.status_code == 200
        assert len(completed.json()["results"]) == 5
        assert "played_at" not in completed.text

        repeated = client.post("/v2/extract-match", files=_files())
        assert repeated.status_code == 202
        assert repeated.json()["job_id"] != first_payload["job_id"]
        assert repeated.json()["deduplicated"] is False


def test_http_api_enforces_per_image_upload_limit() -> None:
    engine = FakeEngine()
    service = MatchJobService(lambda: engine)
    app = create_app(service=service, settings=APISettings(max_upload_bytes=4))

    with TestClient(app) as client:
        response = client.post("/v2/extract-match", files=_files(b"oversized"))

    assert response.status_code == 413
    assert engine.calls == 0


def test_http_api_protects_uploads_and_results_but_keeps_health_available() -> None:
    service = MatchJobService(lambda: FakeEngine())
    valid_key = "-".join(("test", "secret", "key", "1234"))
    incorrect_key = "-".join(("incorrect", "key", "1234"))
    app = create_app(
        service=service,
        settings=APISettings(api_key=valid_key, performance_profile="fast-cpu"),
    )

    with TestClient(app) as client:
        health = client.get("/v2/health")
        assert health.status_code == 200
        assert health.json()["authentication_required"] is True
        assert health.json()["runtime"]["selected_profile"] == "fast-cpu"

        assert client.post("/v2/extract-match", files=_files()).status_code == 401
        assert (
            client.post(
                "/v2/extract-match",
                files=_files(),
                headers={"X-Nexus-API-Key": incorrect_key},
            ).status_code
            == 401
        )
        accepted = client.post(
            "/v2/extract-match",
            files=_files(),
            headers={"Authorization": f"Bearer {valid_key}"},
        )
        assert accepted.status_code == 202
        job_id = accepted.json()["job_id"]
        _wait_for(service, job_id, JobStatus.COMPLETED)

        assert client.get(f"/v2/jobs/{job_id}").status_code == 401
        result = client.get(
            f"/v2/jobs/{job_id}/result",
            headers={"X-Nexus-API-Key": valid_key},
        )
        assert result.status_code == 200


def test_api_key_rejects_short_secrets() -> None:
    try:
        APISettings(api_key="too-short")
    except ValueError as exc:
        assert "at least 16 characters" in str(exc)
    else:
        raise AssertionError("short API key was accepted")


def test_production_mode_rejects_a_missing_api_key() -> None:
    with pytest.raises(ValueError, match="NEXUS_API_KEY is required"):
        APISettings(require_api_key=True)


def test_settings_load_external_runtime_assets_and_required_key_from_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    key = "nxs_" + "a" * 43
    monkeypatch.setenv("NEXUS_API_KEY", key)
    monkeypatch.setenv("NEXUS_REQUIRE_API_KEY", "true")
    monkeypatch.setenv("NEXUS_RUNTIME_ASSETS_ROOT", str(tmp_path))

    settings = APISettings.from_env()

    assert settings.api_key == key
    assert settings.require_api_key is True
    assert settings.runtime_assets_root == tmp_path


def test_settings_load_api_key_from_secret_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    key = "nxs_" + "b" * 43
    key_file = tmp_path / "api-key"
    key_file.write_text(key + "\n", encoding="utf-8")
    monkeypatch.delenv("NEXUS_API_KEY", raising=False)
    monkeypatch.setenv("NEXUS_API_KEY_FILE", str(key_file))
    monkeypatch.setenv("NEXUS_REQUIRE_API_KEY", "true")

    settings = APISettings.from_env()

    assert settings.api_key == key


def test_settings_reject_ambiguous_api_key_sources(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    key_file = tmp_path / "api-key"
    key_file.write_text("nxs_" + "c" * 43, encoding="utf-8")
    monkeypatch.setenv("NEXUS_API_KEY", "nxs_" + "d" * 43)
    monkeypatch.setenv("NEXUS_API_KEY_FILE", str(key_file))

    with pytest.raises(ValueError, match="only one"):
        APISettings.from_env()


def test_uncertified_runtime_is_blocked_without_explicit_validation_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = resolve_runtime_profile(
        "nvidia-cuda",
        available_providers=("CUDAExecutionProvider", "CPUExecutionProvider"),
    )
    app_module = import_module("nexus_v2.api.app")
    monkeypatch.setattr(app_module, "resolve_runtime_profile", lambda _requested: runtime)
    service = MatchJobService(lambda: FakeEngine())

    with pytest.raises(RuntimeError, match="has not passed this server"):
        create_app(service=service, settings=APISettings(performance_profile="fast-cpu"))

    application = create_app(
        service=service,
        settings=APISettings(
            performance_profile="fast-cpu",
            allow_uncertified_runtime=True,
        ),
    )
    assert application is not None


def test_production_engine_wires_vectorized_runtime_into_hero_matcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_module = import_module("nexus_v2.api.app")
    captured: dict[str, object] = {}

    def fake_engine(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    setup = SimpleNamespace(
        prototype_manifest=Path("prototype-manifest.json"),
        matcher_config=VisualMatcherConfig(),
    )
    monkeypatch.setattr(app_module, "resolve_hero_recognition", lambda **_kwargs: setup)
    item_setup = SimpleNamespace(prototype_manifest=Path("item-prototype-manifest.json"))
    monkeypatch.setattr(app_module, "resolve_item_recognition", lambda **_kwargs: item_setup)
    monkeypatch.setattr(app_module, "NexusV2Engine", fake_engine)
    runtime = resolve_runtime_profile(
        "fast-cpu-vectorized", available_providers=("CPUExecutionProvider",)
    )

    app_module.build_production_engine(
        APISettings(project_root=Path("/project")), runtime=runtime
    )

    config = captured["hero_matcher_config"]
    assert isinstance(config, VisualMatcherConfig)
    assert config.hero_scoring_backend == "vectorized"
    assert config.vectorized_chunk_size == 256
    assert captured["item_prototypes"] == item_setup.prototype_manifest
    assert captured["rapidocr_intra_op_num_threads"] == 1
    assert captured["rapidocr_inter_op_num_threads"] == 1


def test_result_schema_rejects_removed_played_at_metadata() -> None:
    payload = _result().model_dump(mode="json")
    payload["metadata"] = {
        "played_at": ExtractedField(status=ExtractionStatus.UNKNOWN).model_dump(mode="json")
    }

    with pytest.raises(ValueError, match="played_at has been removed"):
        ExtractionResult.model_validate(payload)
