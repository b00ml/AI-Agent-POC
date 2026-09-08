"""
Repository 层：审核结果和状态查询
"""
from typing import Dict, Any, Optional
import json
from pathlib import Path


class AuditRepository:
    """审核结果数据访问层"""

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.reports_dir = self.output_dir / "reports"
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def get_results(self) -> Dict[str, Any]:
        """获取审核结果列表"""
        path = self.reports_dir / "m2_audit_report.json"
        if not path.exists():
            return {"total": 0, "results": []}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def get_status_map(self) -> Dict[str, Any]:
        """获取审核状态映射"""
        from core.m2_processor import load_audit_status
        return load_audit_status()

    def save_status_map(self, status_map: Dict[str, Any]):
        """保存审核状态映射"""
        from core.m2_processor import save_audit_status
        save_audit_status(status_map)

    def get_pending_human(self) -> Dict[str, Any]:
        """获取待人工终审列表"""
        path = self.reports_dir / "m2_pending_human.json"
        if not path.exists():
            return {"count": 0, "pending": []}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_pending_human(self, data: Dict[str, Any]):
        """保存待人工终审列表"""
        from core.m2_processor import _atomic_write_json
        path = self.reports_dir / "m2_pending_human.json"
        _atomic_write_json(str(path), data)

    def remove_from_pending_human(self, run_id: str):
        """从待人工终审列表移除指定 run"""
        data = self.get_pending_human()
        data["pending"] = [
            p for p in data.get("pending", [])
            if p.get("workflowRunId") != run_id
        ]
        data["count"] = len(data["pending"])
        self.save_pending_human(data)

    def update_claim_status(self, claim_id: str, result: str, ai_review: Optional[Dict[str, Any]] = None, written_back: bool = False):
        """更新单条报销单审核状态"""
        import time
        status_map = self.get_status_map()
        status_map[claim_id] = {
            "result": result,
            "aiReview": ai_review,
            "writtenBack": written_back,
            "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        }
        self.save_status_map(status_map)
