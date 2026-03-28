from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import threading
import time
from typing import Any
from uuid import uuid4

from ..config.runtime import get_runtime_settings
from ..context.execution import (
    ExtractionCancelledError,
    clear_execution_hooks,
    set_execution_hooks,
)
from .extraction import execute_extraction_request


def _now_ts() -> float:
    return time.time()


@dataclass
class ExtractionJob:
    job_id: str
    status: str
    document_code: str
    model: str | None
    created_at: float
    updated_at: float
    progress: str = "queued"
    progress_detail: str = ""
    cancel_requested: bool = False
    result: dict[str, Any] | None = None
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "document_code": self.document_code,
            "model": self.model,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "progress": self.progress,
            "progress_detail": self.progress_detail,
            "cancel_requested": self.cancel_requested,
            "result": self.result,
            "error": self.error,
        }


_JOBS: dict[str, ExtractionJob] = {}
_JOBS_LOCK = threading.Lock()
_JOB_EXECUTOR: ThreadPoolExecutor | None = None
_TERMINAL_JOB_STATUSES = frozenset({"completed", "failed", "cancelled"})


def _get_job_executor() -> ThreadPoolExecutor:
    global _JOB_EXECUTOR
    if _JOB_EXECUTOR is None:
        max_workers = max(1, get_runtime_settings().web_job_max_workers)
        _JOB_EXECUTOR = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="doc-extractor-job",
        )
    return _JOB_EXECUTOR


def _store_job(job: ExtractionJob) -> None:
    with _JOBS_LOCK:
        _JOBS[job.job_id] = job
        _prune_jobs_locked()


def _update_job(job_id: str, **changes: Any) -> None:
    with _JOBS_LOCK:
        job = _JOBS[job_id]
        for key, value in changes.items():
            setattr(job, key, value)
        job.updated_at = _now_ts()
        _prune_jobs_locked()


def _get_job(job_id: str) -> ExtractionJob:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return job


def _prune_jobs_locked() -> None:
    runtime = get_runtime_settings()
    retention_s = max(0, int(runtime.web_job_retention_s))
    max_stored = max(1, int(runtime.web_job_max_stored))
    now = _now_ts()

    expired_job_ids = [
        job_id
        for job_id, job in _JOBS.items()
        if job.status in _TERMINAL_JOB_STATUSES and retention_s and (now - job.updated_at) > retention_s
    ]
    for job_id in expired_job_ids:
        _JOBS.pop(job_id, None)

    terminal_jobs = sorted(
        (
            (job.updated_at, job.created_at, job_id)
            for job_id, job in _JOBS.items()
            if job.status in _TERMINAL_JOB_STATUSES
        )
    )
    while len(_JOBS) > max_stored and terminal_jobs:
        _, _, job_id = terminal_jobs.pop(0)
        _JOBS.pop(job_id, None)


def _is_cancel_requested(job_id: str) -> bool:
    return _get_job(job_id).cancel_requested


def _mark_cancelled(job_id: str) -> None:
    _update_job(
        job_id,
        status="cancelled",
        progress="cancelled",
        progress_detail="Cancelled by user.",
        error="Cancelled by user.",
        result=None,
    )


def _report_job_progress(job_id: str, stage: str, detail: str = "") -> None:
    try:
        job = _get_job(job_id)
    except KeyError:
        return
    if job.status in {"completed", "failed", "cancelled"}:
        return
    _update_job(job_id, progress=stage, progress_detail=detail)


def _run_job(job_id: str, *, document_code: str, ocr_draft: str, model: str | None) -> None:
    if _is_cancel_requested(job_id):
        _mark_cancelled(job_id)
        return

    _update_job(
        job_id,
        status="running",
        progress="routing",
        progress_detail="Selecting model and document handler.",
    )
    set_execution_hooks(
        progress_callback=lambda stage, detail="": _report_job_progress(job_id, stage, detail),
        cancel_check=lambda: _is_cancel_requested(job_id),
    )
    try:
        response = execute_extraction_request(
            document_code=document_code,
            ocr_draft=ocr_draft,
            model=model,
        )
    except ExtractionCancelledError:
        _mark_cancelled(job_id)
        return
    except Exception as exc:
        _update_job(
            job_id,
            status="failed",
            progress="failed",
            progress_detail="Extraction failed before a result was produced.",
            error=str(exc),
            result=None,
        )
        return
    finally:
        clear_execution_hooks()

    if _is_cancel_requested(job_id):
        _mark_cancelled(job_id)
        return

    if response.get("status") == "failed":
        _update_job(
            job_id,
            status="failed",
            progress="failed",
            progress_detail="Extraction finished with an error response.",
            error=response.get("error", "Extraction failed"),
            result=response,
        )
        return

    _update_job(
        job_id,
        status="completed",
        progress="completed",
        progress_detail="Extraction completed successfully.",
        result=response,
        error="",
    )


def submit_web_extraction_job(
    *,
    document_code: str,
    ocr_draft: str,
    model: str | None = None,
    background: bool = True,
) -> dict[str, Any]:
    job = ExtractionJob(
        job_id=uuid4().hex,
        status="queued",
        document_code=document_code,
        model=model,
        created_at=_now_ts(),
        updated_at=_now_ts(),
    )
    _store_job(job)

    if background:
        _get_job_executor().submit(
            _run_job,
            job.job_id,
            document_code=document_code,
            ocr_draft=ocr_draft,
            model=model,
        )
    else:
        _run_job(
            job.job_id,
            document_code=document_code,
            ocr_draft=ocr_draft,
            model=model,
        )

    return job.to_dict()


def get_web_extraction_job(job_id: str) -> dict[str, Any]:
    return _get_job(job_id).to_dict()


def cancel_web_extraction_job(job_id: str) -> dict[str, Any]:
    job = _get_job(job_id)
    if job.status in {"completed", "failed", "cancelled"}:
        return job.to_dict()

    _update_job(
        job_id,
        cancel_requested=True,
        progress="cancelling" if job.status == "running" else "cancelled",
        progress_detail=(
            "Waiting for the current step to finish before stopping."
            if job.status == "running"
            else "Cancelled before extraction started."
        ),
    )
    if job.status == "queued":
        _mark_cancelled(job_id)
    return get_web_extraction_job(job_id)
