"""
Repository 层：Workflow 运行记录查询
"""
from typing import Optional, Dict, Any
from core.workflow_store import WorkflowRunStore


class WorkflowRepository:
    """Workflow 运行记录数据访问层"""

    def __init__(self, db_path: str):
        self.store = WorkflowRunStore(db_path)

    def get(self, run_id: str) -> Optional[Dict[str, Any]]:
        """获取 workflow 运行记录"""
        return self.store.get(run_id)

    def latest_for_claim(self, claim_id: str) -> Optional[Dict[str, Any]]:
        """获取指定单据的最新 workflow 运行记录"""
        return self.store.latest_for_claim(claim_id)

    def list_by_claim(self, claim_id: str) -> list:
        """获取指定单据的所有 workflow 运行记录"""
        return self.store.list_by_claim(claim_id)
