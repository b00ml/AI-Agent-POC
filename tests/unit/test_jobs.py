"""SQLite job state tests. No ERP, OCR, LLM, or HTTP calls are made."""

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app import job_store, jobs


def _use_temp_db(monkeypatch, tmp_path):
    monkeypatch.setattr(job_store, "DB_PATH", tmp_path / "jobs.db")
    monkeypatch.setattr(job_store, "_SCHEMA_READY", False)


def test_job_progress_and_json_result_roundtrip(monkeypatch, tmp_path):
    _use_temp_db(monkeypatch, tmp_path)
    job_id = job_store.create("m2-audit")
    job_store.update(
        job_id,
        status="succeeded",
        total=2,
        processed=2,
        phase="done",
        results_json='{"total": 2, "results": [{"claimId": "BX-1"}]}',
    )

    job = job_store.get(job_id)
    assert job["jobId"] == job_id
    assert job["status"] == "done"
    assert job["processed"] == 2
    assert job["results"]["results"][0]["claimId"] == "BX-1"
    assert job["cancelRequested"] is False
    assert job["createdAt"]
    assert job["updatedAt"]


def test_startup_marks_interrupted_work_and_finalizes_cancellation(monkeypatch, tmp_path):
    _use_temp_db(monkeypatch, tmp_path)
    running_id = job_store.create("m2-audit")
    job_store.update(running_id, status="running")
    cancelling_id = job_store.create("m3-ai-scan")
    job_store.update(cancelling_id, status="running")
    assert job_store.cancel(cancelling_id) is True

    # Simulate a prior process being interrupted before the next local startup.
    job_store.init_db()

    running = job_store.get(running_id)
    cancelled = job_store.get(cancelling_id)
    assert running["status"] == "error"
    assert "重启" in running["error"]
    assert cancelled["status"] == "cancelled"


def test_bounded_worker_claims_and_completes_job(monkeypatch, tmp_path):
    _use_temp_db(monkeypatch, tmp_path)
    monkeypatch.setattr(jobs, "_INITIALIZED", False)
    completed = threading.Event()

    job_id = jobs.start_job("unit-job", lambda _: completed.set())

    assert completed.wait(timeout=2)
    deadline = time.monotonic() + 2
    job = job_store.get(job_id)
    while job is not None and job["status"] == "running" and time.monotonic() < deadline:
        time.sleep(0.01)
        job = job_store.get(job_id)
    assert job is not None
    assert job["status"] == "done"
    assert job["attempt"] == 1


def test_cancelled_queued_job_is_not_executed(monkeypatch, tmp_path):
    _use_temp_db(monkeypatch, tmp_path)
    job_id = job_store.create("unit-job")
    assert job_store.cancel(job_id)
    assert job_store.claim(job_id) is False
    assert job_store.complete(job_id, "cancelled") is True
    job = job_store.get(job_id)
    assert job is not None
    assert job["status"] == "cancelled"
