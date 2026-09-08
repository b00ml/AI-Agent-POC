"""SQLite-backed job records for the single-node POC worker."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


# job_store.py lives at <repo>/backend/app/, so parents[2] is the repo root.
DB_PATH = Path(__file__).resolve().parents[2] / "output" / "runtime" / "jobs.db"
LOCK = threading.RLock()
_SCHEMA_READY = False


_STATUS_TO_API = {
    "queued": "queued",
    "running": "running",
    "succeeded": "done",
    "failed": "error",
    # Version 0 of this local store wrote `error` directly. Keep old runtime
    # files readable while all new writes use the canonical `failed` state.
    "error": "error",
    "cancel_requested": "cancel_requested",
    "cancelled": "cancelled",
}

_VALID_STATUSES = frozenset(_STATUS_TO_API)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _ensure_schema() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with LOCK:
        if _SCHEMA_READY:
            return
        with _connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS jobs ("
                "id TEXT PRIMARY KEY, name TEXT NOT NULL, status TEXT NOT NULL, "
                "total INTEGER NOT NULL DEFAULT 0, processed INTEGER NOT NULL DEFAULT 0, "
                "phase TEXT NOT NULL DEFAULT 'pending', results_json TEXT, error TEXT, "
                "cancel_requested INTEGER NOT NULL DEFAULT 0, attempt INTEGER NOT NULL DEFAULT 0, "
                "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
            if "attempt" not in columns:
                conn.execute("ALTER TABLE jobs ADD COLUMN attempt INTEGER NOT NULL DEFAULT 0")
        _SCHEMA_READY = True


def init_db() -> None:
    """Initialize storage and mark work interrupted by a prior process exit."""
    _ensure_schema()
    with _connect() as conn:
        conn.execute(
            "UPDATE jobs SET status = 'failed', error = COALESCE(error, '服务重启导致任务中断，请重新提交'), "
            "updated_at = ? WHERE status IN ('queued', 'running')",
            (_now(),),
        )
        conn.execute(
            "UPDATE jobs SET status = 'cancelled', updated_at = ? WHERE status = 'cancel_requested'",
            (_now(),),
        )


def create(name: str) -> str:
    _ensure_schema()
    job_id = uuid.uuid4().hex[:12]
    now = _now()
    with LOCK, _connect() as conn:
        conn.execute(
            "INSERT INTO jobs(id, name, status, created_at, updated_at) VALUES (?, ?, 'queued', ?, ?)",
            (job_id, name, now, now),
        )
    return job_id


def update(job_id: str, **fields: Any) -> None:
    _ensure_schema()
    allowed = {
        "status", "total", "processed", "phase", "results_json", "error", "cancel_requested",
    }
    fields = {k: v for k, v in fields.items() if k in allowed}
    if "status" in fields and fields["status"] not in _VALID_STATUSES:
        raise ValueError(f"unsupported job status: {fields['status']}")
    if not fields:
        return
    fields["updated_at"] = _now()
    values = list(fields.values()) + [job_id]
    with LOCK, _connect() as conn:
        conn.execute(f"UPDATE jobs SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?", values)


def claim(job_id: str) -> bool:
    """Transition a queued job to running exactly once within the SQLite database."""
    _ensure_schema()
    with LOCK, _connect() as conn:
        result = conn.execute(
            "UPDATE jobs SET status = 'running', attempt = attempt + 1, updated_at = ? "
            "WHERE id = ? AND status = 'queued'",
            (_now(), job_id),
        )
    return result.rowcount == 1


def complete(job_id: str, status: str, *, error: Optional[str] = None) -> bool:
    """Finish a claimed job without allowing terminal states to be overwritten."""
    if status not in {"succeeded", "failed", "cancelled"}:
        raise ValueError(f"unsupported terminal status: {status}")
    _ensure_schema()
    fields = ["status = ?", "updated_at = ?"]
    values: list[Any] = [status, _now()]
    if error is not None:
        fields.append("error = ?")
        values.append(error[:500])
    values.append(job_id)
    with LOCK, _connect() as conn:
        result = conn.execute(
            f"UPDATE jobs SET {', '.join(fields)} WHERE id = ? "
            "AND status IN ('running', 'cancel_requested')",
            values,
        )
    return result.rowcount == 1


def get(job_id: str) -> Optional[Dict[str, Any]]:
    _ensure_schema()
    with LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not row:
        return None
    result = dict(row)
    # Keep the SQLite column name private; API response models expose jobId.
    result["jobId"] = result.pop("id")
    raw = result.pop("results_json", None)
    result["results"] = json.loads(raw) if raw else None
    result["createdAt"] = result.pop("created_at")
    result["updatedAt"] = result.pop("updated_at")
    result["cancelRequested"] = bool(result.pop("cancel_requested"))
    result["status"] = _STATUS_TO_API[result["status"]]
    return result


def cancel(job_id: str) -> bool:
    _ensure_schema()
    with LOCK, _connect() as conn:
        result = conn.execute(
            "UPDATE jobs SET cancel_requested = 1, status = 'cancel_requested', updated_at = ? "
            "WHERE id = ? AND status IN ('queued', 'running')",
            (_now(), job_id),
        )
    return result.rowcount == 1


def cancelled(job_id: str) -> bool:
    job = get(job_id)
    return bool(job and job.get("cancelRequested"))
