"""Persistent single-worker match extraction queue."""

from __future__ import annotations

import hashlib
import logging
import queue
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol

from nexus_v2.schemas.result import ExtractionResult

MATCH_ROLES = ("hero_item", "overall", "dps", "farm", "team")
_LOGGER = logging.getLogger(__name__)


class MatchEngine(Protocol):
    def extract_match(self, sources: tuple[bytes, ...]) -> tuple[ExtractionResult, ...]: ...


class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class JobSubmission:
    job_id: str
    status: JobStatus
    deduplicated: bool


@dataclass(frozen=True)
class JobSnapshot:
    job_id: str
    status: JobStatus
    submitted_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    result: tuple[ExtractionResult, ...] | None
    error: str | None
    source_bytes_retained: int


@dataclass
class _Job:
    job_id: str
    key: str
    sources: tuple[bytes, ...]
    status: JobStatus
    submitted_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: tuple[ExtractionResult, ...] | None = None
    error: str | None = None

    def snapshot(self) -> JobSnapshot:
        return JobSnapshot(
            job_id=self.job_id,
            status=self.status,
            submitted_at=self.submitted_at,
            started_at=self.started_at,
            completed_at=self.completed_at,
            result=self.result,
            error=self.error,
            source_bytes_retained=sum(len(source) for source in self.sources),
        )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def active_match_key(sources: tuple[bytes, ...]) -> str:
    """Hash the ordered semantic screen roles and encoded bytes for active deduplication."""

    if len(sources) != len(MATCH_ROLES):
        raise ValueError(f"match extraction requires exactly {len(MATCH_ROLES)} screenshots")
    digest = hashlib.sha256(b"nexus-v2-active-match-v1\0")
    for role, source in zip(MATCH_ROLES, sources, strict=True):
        if not source:
            raise ValueError(f"{role} screenshot is empty")
        role_bytes = role.encode("ascii")
        digest.update(len(role_bytes).to_bytes(2, "big"))
        digest.update(role_bytes)
        digest.update(len(source).to_bytes(8, "big"))
        digest.update(hashlib.sha256(source).digest())
    return digest.hexdigest()


class MatchJobService:
    """Own one preloaded engine and serialize heavy match extractions through one worker."""

    def __init__(
        self,
        engine_factory: Callable[[], MatchEngine],
        *,
        max_retained_jobs: int = 64,
    ) -> None:
        if max_retained_jobs < 1:
            raise ValueError("max_retained_jobs must be positive")
        self._engine_factory = engine_factory
        self._max_retained_jobs = max_retained_jobs
        self._lock = threading.RLock()
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._jobs: dict[str, _Job] = {}
        self._active_by_key: dict[str, str] = {}
        self._engine: MatchEngine | None = None
        self._thread: threading.Thread | None = None
        self._started = False

    def start(self) -> None:
        """Synchronously preload the engine, then start the sole extraction worker."""

        with self._lock:
            if self._started:
                return
            self._engine = self._engine_factory()
            self._started = True
            self._thread = threading.Thread(
                target=self._worker_loop,
                name="nexus-match-worker-1",
                daemon=True,
            )
            self._thread.start()

    def stop(self, *, timeout: float = 5.0) -> None:
        with self._lock:
            if not self._started:
                return
            thread = self._thread
            self._queue.put(None)
        if thread is not None:
            thread.join(timeout=timeout)
        with self._lock:
            if thread is not None and thread.is_alive():
                _LOGGER.warning("match worker did not stop within %.1f seconds", timeout)
                return
            self._started = False
            self._thread = None
            self._engine = None

    def submit(self, sources: tuple[bytes, ...]) -> JobSubmission:
        key = active_match_key(sources)
        with self._lock:
            if not self._started:
                raise RuntimeError("match job service is not started")
            active_id = self._active_by_key.get(key)
            if active_id is not None:
                active = self._jobs[active_id]
                return JobSubmission(
                    job_id=active.job_id,
                    status=active.status,
                    deduplicated=True,
                )
            job_id = uuid.uuid4().hex
            job = _Job(
                job_id=job_id,
                key=key,
                sources=sources,
                status=JobStatus.QUEUED,
                submitted_at=_utc_now(),
            )
            self._jobs[job_id] = job
            self._active_by_key[key] = job_id
            self._queue.put(job_id)
            return JobSubmission(job_id=job_id, status=job.status, deduplicated=False)

    def get(self, job_id: str) -> JobSnapshot:
        with self._lock:
            try:
                return self._jobs[job_id].snapshot()
            except KeyError as exc:
                raise KeyError(f"unknown match job: {job_id}") from exc

    def health(self) -> dict[str, object]:
        with self._lock:
            thread = self._thread
            queued = sum(job.status is JobStatus.QUEUED for job in self._jobs.values())
            processing = sum(job.status is JobStatus.PROCESSING for job in self._jobs.values())
            healthy = self._started and thread is not None and thread.is_alive()
            return {
                "status": "ok" if healthy else "down",
                "engine_loaded": self._engine is not None,
                "worker_alive": thread is not None and thread.is_alive(),
                "max_parallel_jobs": 1,
                "queued_jobs": queued,
                "processing_jobs": processing,
                "completed_result_cache": False,
                "active_deduplication": "ordered_role_and_source_sha256",
            }

    def _worker_loop(self) -> None:
        while True:
            job_id = self._queue.get()
            try:
                if job_id is None:
                    return
                self._run_job(job_id)
            finally:
                self._queue.task_done()

    def _run_job(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = JobStatus.PROCESSING
            job.started_at = _utc_now()
            engine = self._engine
        if engine is None:
            self._finish_failed(job_id, "persistent engine is unavailable")
            return
        try:
            result = engine.extract_match(job.sources)
        except Exception:
            _LOGGER.exception("match extraction job %s failed", job_id)
            self._finish_failed(job_id, "match extraction failed")
            return
        with self._lock:
            job = self._jobs[job_id]
            job.result = result
            job.status = JobStatus.COMPLETED
            job.completed_at = _utc_now()
            job.sources = ()
            self._active_by_key.pop(job.key, None)
            self._trim_terminal_jobs()

    def _finish_failed(self, job_id: str, error: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.error = error
            job.status = JobStatus.FAILED
            job.completed_at = _utc_now()
            job.sources = ()
            self._active_by_key.pop(job.key, None)
            self._trim_terminal_jobs()

    def _trim_terminal_jobs(self) -> None:
        terminal = [
            job_id
            for job_id, job in self._jobs.items()
            if job.status in {JobStatus.COMPLETED, JobStatus.FAILED}
        ]
        excess = len(terminal) - self._max_retained_jobs
        for job_id in terminal[: max(0, excess)]:
            del self._jobs[job_id]


__all__ = [
    "JobSnapshot",
    "JobStatus",
    "JobSubmission",
    "MATCH_ROLES",
    "MatchJobService",
    "active_match_key",
]
