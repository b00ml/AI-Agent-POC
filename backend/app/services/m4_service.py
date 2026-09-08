"""
M4 银行对账业务逻辑服务
"""
import os
import json
from pathlib import Path
from typing import Dict, Any

from app.schemas.m4 import ReconcileRequest
from app.repositories.artifact import ArtifactRepository


class M4Service:
    """M4 银行对账服务"""

    def __init__(self, output_dir: str, bank_dir: str):
        """
        Args:
            output_dir: 输出目录根路径
            bank_dir: 银行流水数据目录
        """
        self.output_dir = Path(output_dir)
        self.bank_dir = Path(bank_dir)
        self.reports_dir = self.output_dir / "reports"
        self.artifacts = ArtifactRepository(self.output_dir)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def reconcile(self, req: ReconcileRequest) -> Dict[str, Any]:
        """执行银行对账"""
        api_key = req.apiKey or os.environ.get("QIHENG_M4_API_KEY")
        if not api_key and os.environ.get("DEMO_MODE", "").strip().lower() in {"1", "true", "yes"}:
            api_key = "demo"
        if not api_key:
            raise ValueError(
                "缺少 M4 专用 API Key（需 receivable:read），请设置 QIHENG_M4_API_KEY"
            )

        from core.client import QihengClient
        from core.m4_processor import M4Processor

        client = QihengClient(api_key=api_key, base_url=req.apiUrl or None)
        processor = M4Processor(client=client)
        result = processor.run(bank_dir=str(self.bank_dir))

        response = dict(result)
        response["artifact"] = self.artifacts.write("m4-reconcile", result)
        return response

    def get_reconcile_results(self) -> Dict[str, Any]:
        """获取最近一次对账结果"""
        envelope = self.artifacts.read_latest("m4-reconcile")
        if envelope is not None and isinstance(envelope.get("payload"), dict):
            return envelope["payload"]
        report_path = self.reports_dir / "m4_result.json"
        if report_path.exists():
            with report_path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        return {
            "matches": [],
            "unidentified": [],
            "message": "请先执行对账"
        }
