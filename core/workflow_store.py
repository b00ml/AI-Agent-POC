"""M2 工作流运行索引：把 claim 与持久化 LangGraph thread 解耦。"""

from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkflowRunStore:
    def __init__(self, path: str) -> None:
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS workflow_runs ("
                "run_id TEXT PRIMARY KEY, claim_id TEXT NOT NULL, status TEXT NOT NULL, "
                "revision INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_workflow_claim ON workflow_runs(claim_id, updated_at)")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def create(self, claim_id: str) -> str:
        run_id = f"wf_{uuid.uuid4().hex}"
        now = _now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO workflow_runs(run_id, claim_id, status, revision, created_at, updated_at) "
                "VALUES (?, ?, 'RUNNING', 0, ?, ?)",
                (run_id, claim_id, now, now),
            )
        return run_id

    def get(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM workflow_runs WHERE run_id = ?", (run_id,)).fetchone()
        return dict(row) if row else None

    def latest_for_claim(self, claim_id: str, status: str = "AWAITING_HUMAN") -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM workflow_runs WHERE claim_id = ? AND status = ? ORDER BY updated_at DESC LIMIT 1",
                (claim_id, status),
            ).fetchone()
        return dict(row) if row else None

    def mark(self, run_id: str, status: str, revision: Optional[int] = None) -> None:
        now = _now()
        with self._connect() as conn:
            if revision is None:
                conn.execute("UPDATE workflow_runs SET status = ?, updated_at = ? WHERE run_id = ?", (status, now, run_id))
            else:
                conn.execute(
                    "UPDATE workflow_runs SET status = ?, revision = ?, updated_at = ? WHERE run_id = ?",
                    (status, revision, now, run_id),
                )

    def claim_decision_revision(self, run_id: str, expected_revision: int) -> bool:
        with self._connect() as conn:
            result = conn.execute(
                "UPDATE workflow_runs SET revision = revision + 1, status = 'RESUMING', updated_at = ? "
                "WHERE run_id = ? AND status = 'AWAITING_HUMAN' AND revision = ?",
                (_now(), run_id, expected_revision),
            )
        return result.rowcount == 1

