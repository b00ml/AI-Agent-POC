"""
M4 银行对账路由
"""
import os
import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class ReconcileRequest(BaseModel):
    apiUrl: str = ""
    apiKey: str = ""


@router.post("/reconcile")
def reconcile(req: ReconcileRequest):
    """执行银行对账（银行流水 CSV + 应收台账，宁缺毋滥）"""
    try:
        from core.client import QihengClient
        from core.m4_processor import M4Processor, BANK_DIR
        api_key = req.apiKey or os.environ.get("QIHENG_M4_API_KEY")
        if not api_key:
            raise HTTPException(
                status_code=400,
                detail="缺少 M4 专用 API Key（需 receivable:read），请设置 QIHENG_M4_API_KEY",
            )
        client = QihengClient(api_key=api_key, base_url=req.apiUrl or None)
        processor = M4Processor(client=client)
        result = processor.run(bank_dir=BANK_DIR)
        # 缓存结果供前端读取
        from pathlib import Path
        out = os.path.join(
            Path(__file__).resolve().parents[3],
            "output", "reports",
        )
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, "m4_result.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/results")
def get_reconcile_results():
    """获取最近一次对账结果"""
    from pathlib import Path
    report_path = os.path.join(
        Path(__file__).resolve().parents[3],
        "output", "reports", "m4_result.json",
    )
    if os.path.exists(report_path):
        with open(report_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"matches": [], "unidentified": [], "message": "请先执行对账"}
