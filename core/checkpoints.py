"""POC 用 SQLite 持久化 LangGraph checkpoint。

当前安装的 langgraph 仅提供 InMemorySaver，没有 sqlite 插件。这里在不引入
额外运行时依赖的前提下，将其完整状态快照写入 SQLite，支持 API 进程重启后
恢复 human gate。它适用于单节点 POC；多 worker 需要替换为官方 Postgres saver。
"""

from __future__ import annotations

import os
import pickle
import sqlite3
import threading
from collections import defaultdict

from langgraph.checkpoint.memory import InMemorySaver

from core.logger import get_logger

logger = get_logger("checkpoints")


class SQLiteCheckpointSaver(InMemorySaver):
    """将 InMemorySaver 的 checkpoint/blob/write 状态持久化到单个 SQLite 行。"""

    def __init__(self, path: str) -> None:
        super().__init__()
        self.path = path
        self._db_lock = threading.RLock()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._init_db()
        self._load()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS checkpoint_snapshots ("
                "id INTEGER PRIMARY KEY CHECK (id = 1), state BLOB NOT NULL, updated_at TEXT NOT NULL)"
            )

    def _load(self) -> None:
        with self._db_lock, self._connect() as conn:
            row = conn.execute("SELECT state FROM checkpoint_snapshots WHERE id = 1").fetchone()
        if not row:
            return
        try:
            storage_data, writes_data, blobs_data = pickle.loads(row[0])
            storage = defaultdict(lambda: defaultdict(dict))
            for thread_id, namespaces in storage_data.items():
                for namespace, checkpoints in namespaces.items():
                    storage[thread_id][namespace].update(checkpoints)
            self.storage = storage
            self.writes = defaultdict(dict, writes_data)
            self.blobs = dict(blobs_data)
        except (pickle.PickleError, TypeError, ValueError) as exc:
            logger.warning("checkpoint 快照不可读，使用空状态: %s", exc)

    def _save(self) -> None:
        storage_data = {
            thread_id: {namespace: dict(checkpoints) for namespace, checkpoints in namespaces.items()}
            for thread_id, namespaces in self.storage.items()
        }
        state = pickle.dumps((storage_data, dict(self.writes), dict(self.blobs)), protocol=pickle.HIGHEST_PROTOCOL)
        with self._db_lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO checkpoint_snapshots(id, state, updated_at) VALUES(1, ?, datetime('now')) "
                "ON CONFLICT(id) DO UPDATE SET state = excluded.state, updated_at = excluded.updated_at",
                (state,),
            )

    def put(self, config, checkpoint, metadata, new_versions):
        with self._db_lock:
            out = super().put(config, checkpoint, metadata, new_versions)
            self._save()
            return out

    def put_writes(self, config, writes, task_id, task_path=""):
        with self._db_lock:
            super().put_writes(config, writes, task_id, task_path)
            self._save()

    def delete_thread(self, thread_id: str) -> None:
        with self._db_lock:
            super().delete_thread(thread_id)
            self._save()
