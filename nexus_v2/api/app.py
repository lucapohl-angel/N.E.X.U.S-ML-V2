"""FastAPI application for asynchronous five-screen match extraction."""

from __future__ import annotations

import os
import secrets
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from http import HTTPStatus
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from nexus_v2.api.jobs import JobSnapshot, JobStatus, MatchJobService
from nexus_v2.engine import NexusV2Engine
from nexus_v2.recognition.modes import resolve_hero_recognition, resolve_item_recognition
from nexus_v2.runtime import RuntimeProfile, resolve_runtime_profile


@dataclass(frozen=True)
class APISettings:
    project_root: Path = Path(__file__).resolve().parents[2]
    max_upload_bytes: int = 50 * 1024 * 1024
    max_retained_jobs: int = 64
    performance_profile: str = "auto"
    api_key: str | None = None
    require_api_key: bool = False
    runtime_assets_root: Path | None = None
    allow_uncertified_runtime: bool = False

    def __post_init__(self) -> None:
        if self.max_upload_bytes < 1:
            raise ValueError("max_upload_bytes must be positive")
        if self.max_retained_jobs < 1:
            raise ValueError("max_retained_jobs must be positive")
        resolve_runtime_profile(self.performance_profile)
        if self.api_key is not None and len(self.api_key) < 16:
            raise ValueError("api_key must contain at least 16 characters")
        if self.require_api_key and self.api_key is None:
            raise ValueError("NEXUS_API_KEY is required for production service startup")

    @classmethod
    def from_env(cls) -> APISettings:
        root = Path(os.environ.get("NEXUS_PROJECT_ROOT", cls.project_root))
        raw_key = os.environ.get("NEXUS_API_KEY")
        raw_key_file = os.environ.get("NEXUS_API_KEY_FILE")
        if raw_key and raw_key_file:
            raise ValueError("configure only one of NEXUS_API_KEY or NEXUS_API_KEY_FILE")
        if raw_key_file:
            key_path = Path(raw_key_file).expanduser()
            try:
                raw_key = key_path.read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise ValueError(f"unable to read NEXUS_API_KEY_FILE: {key_path}") from exc
            if not raw_key:
                raise ValueError("NEXUS_API_KEY_FILE is empty")
        raw_runtime_root = os.environ.get("NEXUS_RUNTIME_ASSETS_ROOT")
        return cls(
            project_root=root,
            max_upload_bytes=int(os.environ.get("NEXUS_MAX_UPLOAD_BYTES", 50 * 1024 * 1024)),
            max_retained_jobs=int(os.environ.get("NEXUS_MAX_RETAINED_JOBS", 64)),
            performance_profile=os.environ.get("NEXUS_PERFORMANCE_PROFILE", "auto"),
            api_key=raw_key if raw_key else None,
            require_api_key=os.environ.get("NEXUS_REQUIRE_API_KEY", "false").lower()
            in {"1", "true", "yes"},
            runtime_assets_root=Path(raw_runtime_root) if raw_runtime_root else None,
            allow_uncertified_runtime=os.environ.get(
                "NEXUS_ALLOW_UNCERTIFIED_RUNTIME", "false"
            ).lower()
            in {"1", "true", "yes"},
        )


class _ResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class JobAccepted(_ResponseModel):
    job_id: str
    status: JobStatus
    deduplicated: bool
    status_url: str
    result_url: str


class JobState(_ResponseModel):
    job_id: str
    status: JobStatus
    submitted_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    error: str | None


def build_production_engine(
    settings: APISettings,
    runtime: RuntimeProfile | None = None,
) -> NexusV2Engine:
    root = settings.project_root.resolve()
    recognition_root = (
        settings.runtime_assets_root.expanduser().resolve()
        if settings.runtime_assets_root is not None
        else root
    )
    resolved_runtime = runtime or resolve_runtime_profile(settings.performance_profile)
    catalog = recognition_root / "catalogs/staging/user-approved-2026-08-01-r2/catalog.json"
    hero_setup = resolve_hero_recognition(
        project_root=recognition_root,
        catalog_path=catalog,
        mode="balanced",
    )
    item_setup = resolve_item_recognition(project_root=recognition_root, catalog_path=catalog)
    hero_matcher_config = replace(
        hero_setup.matcher_config,
        hero_scoring_backend=resolved_runtime.hero_scoring_backend,
        vectorized_chunk_size=resolved_runtime.vectorized_chunk_size,
    )
    return NexusV2Engine(
        profiles_root=root / "profiles",
        catalog_path=catalog,
        hero_prototypes=hero_setup.prototype_manifest,
        item_prototypes=item_setup.prototype_manifest,
        hero_matcher_config=hero_matcher_config,
        use_rapidocr=True,
        rapidocr_text_detection=resolved_runtime.rapidocr_text_detection,
        rapidocr_use_cuda=resolved_runtime.rapidocr_use_cuda,
        rapidocr_intra_op_num_threads=resolved_runtime.rapidocr_intra_op_num_threads,
        rapidocr_inter_op_num_threads=resolved_runtime.rapidocr_inter_op_num_threads,
        runtime_versions=resolved_runtime.provenance_versions(),
    )


def _job_state(snapshot: JobSnapshot) -> JobState:
    return JobState(
        job_id=snapshot.job_id,
        status=snapshot.status,
        submitted_at=snapshot.submitted_at,
        started_at=snapshot.started_at,
        completed_at=snapshot.completed_at,
        error=snapshot.error,
    )


async def _read_upload(upload: UploadFile, *, limit: int, role: str) -> bytes:
    try:
        content = await upload.read(limit + 1)
    finally:
        await upload.close()
    if not content:
        raise HTTPException(HTTPStatus.UNPROCESSABLE_ENTITY, f"{role} screenshot is empty")
    if len(content) > limit:
        raise HTTPException(
            HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            f"{role} screenshot exceeds the {limit}-byte upload limit",
        )
    return content


def create_app(
    *,
    service: MatchJobService | None = None,
    settings: APISettings | None = None,
    engine_factory: Callable[[], NexusV2Engine] | None = None,
) -> FastAPI:
    resolved_settings = settings or APISettings()
    runtime = resolve_runtime_profile(resolved_settings.performance_profile)
    if (
        not runtime.certification.selected_output_certified
        and not resolved_settings.allow_uncertified_runtime
    ):
        raise RuntimeError(
            f"performance profile {runtime.selected.value!r} has not passed this server's "
            "reviewed-corpus certification; set NEXUS_ALLOW_UNCERTIFIED_RUNTIME=true only "
            "for controlled validation"
        )
    resolved_factory = engine_factory or (
        lambda: build_production_engine(resolved_settings, runtime)
    )
    jobs = service or MatchJobService(
        resolved_factory,
        max_retained_jobs=resolved_settings.max_retained_jobs,
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        jobs.start()
        application.state.match_jobs = jobs
        try:
            yield
        finally:
            jobs.stop()

    application = FastAPI(
        title="N.E.X.U.S-ML V2",
        version="2.0.0a0",
        lifespan=lifespan,
    )

    async def authorize(
        authorization: Annotated[str | None, Header()] = None,
        x_nexus_api_key: Annotated[str | None, Header()] = None,
    ) -> None:
        expected = resolved_settings.api_key
        if expected is None:
            return
        bearer = None
        if authorization is not None and authorization.startswith("Bearer "):
            bearer = authorization.removeprefix("Bearer ")
        supplied = x_nexus_api_key or bearer
        if supplied is None or not secrets.compare_digest(supplied, expected):
            raise HTTPException(
                HTTPStatus.UNAUTHORIZED,
                "valid server API credentials are required",
                headers={"WWW-Authenticate": "Bearer"},
            )

    @application.get("/v2/health")
    def health() -> dict[str, object]:
        return {
            **jobs.health(),
            "authentication_required": resolved_settings.api_key is not None,
            "runtime": runtime.public_dict(),
        }

    @application.post(
        "/v2/extract-match",
        response_model=JobAccepted,
        status_code=HTTPStatus.ACCEPTED,
        dependencies=[Depends(authorize)],
    )
    async def extract_match(
        hero_item: Annotated[UploadFile, File(description="Hero and item screen")],
        overall: Annotated[UploadFile, File(description="Overall statistics screen")],
        dps: Annotated[UploadFile, File(description="DPS statistics screen")],
        farm: Annotated[UploadFile, File(description="Farm statistics screen")],
        team: Annotated[UploadFile, File(description="Team statistics screen")],
    ) -> JobAccepted:
        uploads = (hero_item, overall, dps, farm, team)
        roles = ("hero_item", "overall", "dps", "farm", "team")
        sources = tuple(
            [
                await _read_upload(upload, limit=resolved_settings.max_upload_bytes, role=role)
                for role, upload in zip(roles, uploads, strict=True)
            ]
        )
        submission = jobs.submit(sources)
        return JobAccepted(
            job_id=submission.job_id,
            status=submission.status,
            deduplicated=submission.deduplicated,
            status_url=f"/v2/jobs/{submission.job_id}",
            result_url=f"/v2/jobs/{submission.job_id}/result",
        )

    @application.get(
        "/v2/jobs/{job_id}",
        response_model=JobState,
        dependencies=[Depends(authorize)],
    )
    def job_status(job_id: str) -> JobState:
        try:
            return _job_state(jobs.get(job_id))
        except KeyError as exc:
            raise HTTPException(HTTPStatus.NOT_FOUND, "match job was not found") from exc

    @application.get(
        "/v2/jobs/{job_id}/result",
        response_model=None,
        dependencies=[Depends(authorize)],
    )
    def job_result(job_id: str) -> JSONResponse:
        try:
            snapshot = jobs.get(job_id)
        except KeyError as exc:
            raise HTTPException(HTTPStatus.NOT_FOUND, "match job was not found") from exc
        if snapshot.status in {JobStatus.QUEUED, JobStatus.PROCESSING}:
            return JSONResponse(
                status_code=HTTPStatus.ACCEPTED,
                content=_job_state(snapshot).model_dump(mode="json"),
            )
        if snapshot.status is JobStatus.FAILED:
            return JSONResponse(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                content=_job_state(snapshot).model_dump(mode="json"),
            )
        if snapshot.result is None:
            raise HTTPException(HTTPStatus.INTERNAL_SERVER_ERROR, "completed job has no result")
        return JSONResponse(
            content={
                "job_id": snapshot.job_id,
                "status": snapshot.status.value,
                "results": [result.model_dump(mode="json") for result in snapshot.result],
            }
        )

    return application


app = create_app(settings=APISettings.from_env())


__all__ = ["APISettings", "app", "build_production_engine", "create_app"]
