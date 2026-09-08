"""
Repository 层：Job 持久化查询
"""
from typing import Optional, Dict, Any

from app.repositories.artifact import ArtifactRepository

__all__ = ["ArtifactRepository", "JobRepository"]


class JobRepository:
    """Job 数据访问层"""

    def __init__(self):
        """初始化并确保数据库 schema"""
        from app.jobs import _ensure_initialized
        _ensure_initialized()

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        """获取任务状态"""
        from app.jobs import get_job
        return get_job(job_id)

    def request_cancel(self, job_id: str) -> bool:
        """请求取消任务"""
        from app.jobs import request_cancel
        return request_cancel(job_id)

    def is_cancel_requested(self, job_id: str) -> bool:
        """检查是否请求取消"""
        from app.jobs import is_cancel_requested
        return is_cancel_requested(job_id)

    def raise_if_cancel_requested(self, job_id: str):
        """如果已请求取消则抛出异常"""
        from app.jobs import raise_if_cancel_requested
        raise_if_cancel_requested(job_id)
