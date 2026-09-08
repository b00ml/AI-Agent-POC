"""Versioned JSON artifact storage for the single-node POC."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from filelock import FileLock


class ArtifactRepository:
    """Persist immutable JSON results and maintain a small latest-pointer index."""

    def __init__(self, output_dir: str | Path):
        self.root = Path(output_dir) / "artifacts"
        self.root.mkdir(parents=True, exist_ok=True)
        self._index_path = self.root / "latest.json"
        self._lock = FileLock(str(self.root / ".artifacts.lock"))
        self._thread_lock = threading.RLock()

    def write(self, artifact_type: str, payload: Dict[str, Any], *, job_id: Optional[str] = None) -> Dict[str, Any]:
        """Write a new artifact revision without overwriting a prior result."""
        safe_type = self._safe_segment(artifact_type, "artifact_type")
        run_id = self._safe_segment(job_id or f"run_{uuid.uuid4().hex[:12]}", "job_id")
        target_dir = self.root / safe_type / run_id

        with self._thread_lock, self._lock:
            target_dir.mkdir(parents=True, exist_ok=True)
            revision = self._next_revision(target_dir)
            artifact_id = f"{safe_type}:{run_id}:r{revision}"
            created_at = datetime.now(timezone.utc).isoformat()
            payload_bytes = json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            metadata = {
                "artifactId": artifact_id,
                "artifactType": safe_type,
                "jobId": job_id,
                "revision": revision,
                "schemaVersion": 1,
                "createdAt": created_at,
                "sha256": hashlib.sha256(payload_bytes).hexdigest(),
            }
            envelope = {"metadata": metadata, "payload": payload}
            relative_path = f"{safe_type}/{run_id}/r{revision}.json"
            self._atomic_write_json(self.root / relative_path, envelope)

            index = self._read_json(self._index_path, {})
            index[safe_type] = {"artifactId": artifact_id, "path": relative_path}
            self._atomic_write_json(self._index_path, index)
            return dict(metadata)

    def read_latest(self, artifact_type: str) -> Optional[Dict[str, Any]]:
        """Return the latest artifact payload and metadata for one result type."""
        safe_type = self._safe_segment(artifact_type, "artifact_type")
        with self._thread_lock, self._lock:
            index = self._read_json(self._index_path, {})
            entry = index.get(safe_type)
            if not entry:
                return None
            envelope = self._read_json(self.root / entry["path"], None)
            if not envelope:
                return None
            return envelope

    @staticmethod
    def _safe_segment(value: str, field: str) -> str:
        if not value or value in {".", ".."} or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for ch in value):
            raise ValueError(f"invalid {field}")
        return value

    @staticmethod
    def _next_revision(target_dir: Path) -> int:
        revisions = []
        for path in target_dir.glob("r*.json"):
            try:
                revisions.append(int(path.stem[1:]))
            except ValueError:
                continue
        return max(revisions, default=0) + 1

    @staticmethod
    def _read_json(path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    @staticmethod
    def _atomic_write_json(path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise
