"""SQLite-backed background jobs for the single-node POC.

The worker remains a daemon thread to keep local startup simple. SQLite is the
source of truth for progress and failures, so polling survives a backend
process restart (unfinished work is explicitly marked failed at startup).
"""

from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Optional

from app import job_store


_INIT_LOCK = threading.Lock()
_INITIALIZED = False


def _positive_int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


_MAX_WORKERS = _positive_int_env("JOB_MAX_WORKERS", 2)
_MAX_PENDING = _positive_int_env("JOB_MAX_PENDING", 16)
_EXECUTOR = ThreadPoolExecutor(max_workers=_MAX_WORKERS, thread_name_prefix="qiheng-job")
# ThreadPoolExecutor uses an unbounded internal queue. This semaphore provides
# the POC's explicit back-pressure boundary for running and pending jobs.
_CAPACITY = threading.BoundedSemaphore(_MAX_WORKERS + _MAX_PENDING)


class JobCancelled(Exception):
    """Raised by a cooperative worker checkpoint after cancellation."""


class JobQueueFull(Exception):
    """Raised when the single-node worker has reached its bounded capacity."""


def _ensure_initialized() -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return
    with _INIT_LOCK:
        if not _INITIALIZED:
            job_store.init_db()
            _INITIALIZED = True


def start_job(name: str, fn: Callable[[str], None]) -> str:
    """Queue a job for the bounded local worker and return its stable id.

    The callable is deliberately not persisted because it closes over a
    request-scoped ERP credential. A process restart marks unfinished work as
    failed instead of pretending that it can safely resume it.
    """
    _ensure_initialized()
    if not _CAPACITY.acquire(blocking=False):
        raise JobQueueFull("任务队列已满，请稍后重试")

    job_id = job_store.create(name)

    def _run() -> None:
        try:
            # A queued job can be cancelled before a worker claims it.
            if not job_store.claim(job_id):
                if is_cancel_requested(job_id):
                    job_store.complete(job_id, "cancelled")
                return
            raise_if_cancel_requested(job_id)
            fn(job_id)
            # Preserve a cancellation request made while the worker was busy.
            job_store.complete(job_id, "cancelled" if is_cancel_requested(job_id) else "succeeded")
        except JobCancelled:
            job_store.complete(job_id, "cancelled")
        except Exception as exc:  # persist failures at the thread boundary
            job_store.complete(job_id, "failed", error=str(exc))
        finally:
            _CAPACITY.release()

    try:
        _EXECUTOR.submit(_run)
    except Exception:
        _CAPACITY.release()
        job_store.update(job_id, status="failed", error="任务调度器不可用")
        raise
    return job_id


def update_progress(
    job_id: str,
    total: int,
    processed: int,
    results: Any = None,
    phase: Optional[str] = None,
) -> None:
    """Persist progress; structured results are encoded at the storage boundary."""
    _ensure_initialized()
    fields: Dict[str, Any] = {"total": total, "processed": processed}
    if phase is not None:
        fields["phase"] = phase
    if results is not None:
        fields["results_json"] = json.dumps(results, ensure_ascii=False)
    job_store.update(job_id, **fields)


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    _ensure_initialized()
    return job_store.get(job_id)


def request_cancel(job_id: str) -> bool:
    """Request cooperative cancellation for a queued/running job."""
    _ensure_initialized()
    return job_store.cancel(job_id)


def is_cancel_requested(job_id: str) -> bool:
    _ensure_initialized()
    return job_store.cancelled(job_id)


def raise_if_cancel_requested(job_id: str) -> None:
    """Let workers stop at an explicit safe boundary."""
    if is_cancel_requested(job_id):
        raise JobCancelled(f"job {job_id} cancellation requested")
