"""Artifact repository tests use a temporary directory only."""

import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.repositories.artifact import ArtifactRepository


def test_artifact_write_is_versioned_and_readable(tmp_path):
    repository = ArtifactRepository(tmp_path)

    first = repository.write("m3-scan", {"run": 1}, job_id="job-1")
    second = repository.write("m3-scan", {"run": 2}, job_id="job-1")
    latest = repository.read_latest("m3-scan")

    assert first["artifactId"] == "m3-scan:job-1:r1"
    assert second["artifactId"] == "m3-scan:job-1:r2"
    assert latest is not None
    assert latest["metadata"]["sha256"]
    assert latest["payload"] == {"run": 2}


def test_parallel_jobs_never_share_artifact_path(tmp_path):
    repository = ArtifactRepository(tmp_path)
    results = []
    lock = threading.Lock()

    def write(job_id: str):
        artifact = repository.write("m3-ai-scan", {"job": job_id}, job_id=job_id)
        with lock:
            results.append(artifact)

    threads = [threading.Thread(target=write, args=(f"job-{index}",)) for index in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert len(results) == 4
    artifact_paths = list((tmp_path / "artifacts" / "m3-ai-scan").glob("job-*/r1.json"))
    assert len(artifact_paths) == 4
