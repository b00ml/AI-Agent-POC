"""
M2 合规审核路由
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

from app.jobs import get_job, raise_if_cancel_requested, request_cancel, start_job, update_progress

router = APIRouter()


class AuditRequest(BaseModel):
    claimIds: List[str]
    apiUrl: str = ""
    apiKey: str = ""
    writeBack: bool = False


class OCRRequest(BaseModel):
    claimId: str
    apiUrl: str = ""
    apiKey: str = ""


class ReviewRequest(BaseModel):
    claimId: str
    decision: str
    comment: Optional[str] = None
    evidence: List[Dict[str, Any]] = Field(default_factory=list)
    aiResult: Optional[str] = None
    aiViolations: List[str] = Field(default_factory=list)
    aiReasons: List[str] = Field(default_factory=list)
    aiConfidence: Optional[float] = None
    apiUrl: str = ""
    apiKey: str = ""


@router.post("/audit")
def audit_claims(req: AuditRequest):
    """执行批量 M2 审核（异步任务，立即返回 jobId，前端轮询进度）"""
    req_data = req.model_dump()

    def worker(job_id: str) -> None:
        from core.client import QihengClient
        from core.m2_processor import M2Processor
        client = QihengClient(
            api_key=req_data["apiKey"], base_url=req_data["apiUrl"] or None
        )
        processor = M2Processor(client=client, use_ocr=True)

        def cb(total: int, processed: int, phase: str = "rules") -> None:
            raise_if_cancel_requested(job_id)
            update_progress(job_id, total, processed, phase=phase)

        results = processor.run(
            claim_ids=req_data["claimIds"],
            write_back=req_data["writeBack"],
            progress_cb=cb,
        )
        update_progress(
            job_id, len(results), len(results),
            results={"results": [r.to_dict() for r in results], "total": len(results)},
            phase="done",
        )

    job_id = start_job("m2-audit", worker)
    return {"jobId": job_id, "status": "running"}


@router.get("/audit-status/{job_id}")
def audit_status(job_id: str):
    """查询 M2 审核任务进度"""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    return job


@router.post("/audit-status/{job_id}/cancel")
def cancel_audit(job_id: str):
    """请求协作式取消；已在执行的外部调用会在当前调用结束后才停止。"""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if not request_cancel(job_id):
        return {"jobId": job_id, "status": job["status"], "cancelRequested": job["cancelRequested"]}
    return {"jobId": job_id, "status": "cancel_requested", "cancelRequested": True}


@router.post("/ocr")
def run_ocr(req: OCRRequest):
    """执行单票 OCR 识别"""
    try:
        from core.invoice_ocr import InvoiceOCREngine
        engine = InvoiceOCREngine()
        result = engine.recognize_claim_invoices(
            req.claimId,
            api_url=req.apiUrl,
            api_key=req.apiKey
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/review")
def submit_review(req: ReviewRequest):
    """
    人工复核回写：把「AI 建议 + 操作人决定」一并写入审核意见记录。
    不影响单据状态（AI/操作人只给意见，ERP 侧人工放行）。
    """
    try:
        from core.client import QihengClient
        client = QihengClient(api_key=req.apiKey, base_url=req.apiUrl or None)

        # 理由 = AI 建议理由 + 操作人意见（覆盖时明确标注）
        reasons = list(req.aiReasons or [])
        note_parts = []
        if req.aiResult and req.aiResult != req.decision:
            note_parts.append(f"AI 建议 {req.aiResult}，操作人决定 {req.decision}")
        if req.comment:
            note_parts.append(f"操作人意见：{req.comment}")
        if note_parts:
            reasons.append("；".join(note_parts))

        # 操作人与 AI 结论一致时保留违规代码，覆盖时置空（人工判断为准）
        violations = list(req.aiViolations or []) if req.decision == req.aiResult else []

        result = client.expense_claims_review(
            claim_id=req.claimId,
            result=req.decision,
            reasons=reasons,
            violations=violations,
            evidence=req.evidence or None,
            confidence=req.aiConfidence,
        )
        return {"status": "success", "claimId": req.claimId, "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/results")
def get_audit_results():
    """获取审核结果（读取本地审核报告）"""
    import os
    import json
    from pathlib import Path
    report_path = os.path.join(
        Path(__file__).resolve().parents[3],
        "output", "reports", "audit_report.json",
    )
    if os.path.exists(report_path):
        with open(report_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {"results": data.get("reviews", []), "generatedAt": data.get("generatedAt")}
    return {"results": [], "message": "请先执行审核"}


@router.get("/status")
def get_audit_status():
    """获取每单审核状态（待审核/AI审核/已写回），供列表页展示"""
    from core.m2_processor import load_audit_status
    status = load_audit_status()
    return {"status": status, "count": len(status)}


class HumanGateResume(BaseModel):
    decision: str
    comment: Optional[str] = None
    expectedRevision: int = Field(ge=0)
    apiUrl: str = ""
    apiKey: str = ""


@router.get("/pending-human")
def get_pending_human():
    """图管线（AGENT_HUMAN_GATE=1）中暂停等待人工终审的单"""
    import os
    import json
    from pathlib import Path
    path = os.path.join(
        Path(__file__).resolve().parents[3],
        "output", "reports", "m2_pending_human.json",
    )
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"count": 0, "pending": []}


def _resume_runner(run_id: str, req: HumanGateResume):
    """Return the hot runner, or reconstruct only the write-back dependencies."""
    from core.workflow import M2GraphRunner

    runner = M2GraphRunner.get_runner(run_id)
    if runner is not None:
        return runner
    if not req.apiKey:
        raise HTTPException(
            status_code=400,
            detail="后端已重启，恢复人工终审需重新提供 ERP API Key；密钥不会写入 workflow checkpoint",
        )
    from core.client import QihengClient
    from data.travel_data import TravelDataManager

    client = QihengClient(api_key=req.apiKey, base_url=req.apiUrl or None)

    def write_back(payload: dict) -> None:
        client.expense_claims_review(
            claim_id=payload.get("claimId", ""),
            result=payload.get("result"),
            reasons=payload.get("reasons") or [],
            confidence=payload.get("confidence"),
            violations=payload.get("violations") or [],
        )

    # Resume continues from human_gate to write_back. It does not reload OCR,
    # policy retrieval, or LLM state; those values are already checkpointed.
    return M2GraphRunner(
        client=client,
        travel_manager=TravelDataManager(client),
        retriever=None,
        llm_reviewer=None,
        write_back_fn=write_back,
    )


def _complete_human_gate(run_id: str, req: HumanGateResume):
    """Apply one revision-checked human decision and synchronize local views."""
    if req.decision not in ("APPROVE", "REJECT", "FLAG"):
        raise HTTPException(status_code=400, detail="decision 必须是 APPROVE/REJECT/FLAG")
    from core.workflow import WORKFLOW_DB
    from core.workflow_store import WorkflowRunStore

    store = WorkflowRunStore(WORKFLOW_DB)
    record = store.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="workflow run 不存在")
    if record["status"] != "AWAITING_HUMAN" or record["revision"] != req.expectedRevision:
        raise HTTPException(status_code=409, detail="人工决定已被提交、已完成或版本已变化，请刷新后重试")
    runner = _resume_runner(run_id, req)
    state = runner.resume(
        run_id,
        decision=req.decision,
        comment=req.comment or "",
        expected_revision=req.expectedRevision,
    )
    if state is None:
        raise HTTPException(status_code=409, detail="人工决定并发冲突或 checkpoint 不存在")

    # 同步每单状态并从待审清单移除
    from core.m2_processor import (
        load_audit_status, save_audit_status, _atomic_write_json,
    )
    import os
    import time
    from pathlib import Path
    status_map = load_audit_status()
    claim_id = record["claim_id"]
    status_map[claim_id] = {
        "result": state.get("final_result"),
        "aiReview": state.get("ai_review"),
        "writtenBack": True,
        "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
    }
    save_audit_status(status_map)

    pending_path = os.path.join(
        Path(__file__).resolve().parents[3],
        "output", "reports", "m2_pending_human.json",
    )
    if os.path.exists(pending_path):
        import json
        with open(pending_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {"count": 0, "pending": []}
    data["pending"] = [
        p for p in (data.get("pending") or []) if p.get("workflowRunId") != run_id
    ]
    data["count"] = len(data["pending"])
    _atomic_write_json(pending_path, data)
    return {
        "status": "success",
        "claimId": claim_id,
        "workflowRunId": run_id,
        "finalResult": state.get("final_result"),
    }


@router.post("/human-gate/run/{run_id}/resume")
def human_gate_resume_run(run_id: str, req: HumanGateResume):
    """Resume a durable LangGraph human gate by immutable workflow run id."""
    return _complete_human_gate(run_id, req)


@router.post("/human-gate/{claim_id}/resume", deprecated=True)
def human_gate_resume_claim(claim_id: str, req: HumanGateResume):
    """2.0 compatibility route; new clients must submit workflowRunId instead."""
    from core.workflow import WORKFLOW_DB
    from core.workflow_store import WorkflowRunStore

    record = WorkflowRunStore(WORKFLOW_DB).latest_for_claim(claim_id)
    if record is None:
        raise HTTPException(status_code=404, detail="该单没有等待人工终审的 workflow run")
    return _complete_human_gate(record["run_id"], req)
