"""
M2 合规审核路由（重构版：使用 Service + Response Model）
"""
import logging

from fastapi import APIRouter, Depends

from app.api_errors import api_error, error_responses
from app.jobs import JobQueueFull
from app.schemas.m2 import (
    AuditRequest, OCRRequest, ReviewRequest, HumanGateResume,
    JobCreatedResponse, JobStatusResponse, JobCancelResponse,
    OCRResponse, ReviewResponse, AuditResultsResponse,
    PendingHumanResponse, HumanGateResumeResponse
)
from app.services import get_m2_service, M2Service

router = APIRouter()
logger = logging.getLogger("api.m2")


@router.post("/audit", response_model=JobCreatedResponse, status_code=202, responses=error_responses(422, 503))
def audit_claims(req: AuditRequest, service: M2Service = Depends(get_m2_service)):
    """执行批量 M2 审核（异步任务，立即返回 jobId，前端轮询进度）"""
    try:
        return service.start_audit(req)
    except JobQueueFull as exc:
        raise api_error(503, "JOB_QUEUE_FULL", str(exc)) from exc


@router.get("/audit-status/{job_id}", response_model=JobStatusResponse, responses=error_responses(404))
def audit_status(job_id: str, service: M2Service = Depends(get_m2_service)):
    """查询 M2 审核任务进度"""
    result = service.get_audit_status(job_id)
    if not result:
        raise api_error(404, "JOB_NOT_FOUND", "任务不存在或已过期")
    return result


@router.post("/audit-status/{job_id}/cancel", response_model=JobCancelResponse, responses=error_responses(404))
def cancel_audit(job_id: str, service: M2Service = Depends(get_m2_service)):
    """请求协作式取消；已在执行的外部调用会在当前调用结束后才停止。"""
    result = service.cancel_audit(job_id)
    if not result:
        raise api_error(404, "JOB_NOT_FOUND", "任务不存在")
    return result


@router.post("/ocr", response_model=OCRResponse, responses=error_responses(422, 500))
def run_ocr(req: OCRRequest, service: M2Service = Depends(get_m2_service)):
    """执行单票 OCR 识别"""
    try:
        return service.run_ocr(req)
    except Exception as exc:
        logger.exception("M2 OCR failed")
        raise api_error(500, "M2_OCR_FAILED", "OCR 处理失败，请使用 requestId 查询日志") from exc


@router.post("/review", response_model=ReviewResponse, responses=error_responses(422, 500))
def submit_review(req: ReviewRequest, service: M2Service = Depends(get_m2_service)):
    """
    人工复核回写：把「AI 建议 + 操作人决定」一并写入审核意见记录。
    不影响单据状态（AI/操作人只给意见，ERP 侧人工放行）。
    """
    try:
        return service.submit_review(req)
    except Exception as exc:
        logger.exception("M2 review write-back failed")
        raise api_error(500, "M2_REVIEW_FAILED", "审核意见回写失败，请使用 requestId 查询日志") from exc


@router.get("/results", response_model=AuditResultsResponse)
def get_audit_results(service: M2Service = Depends(get_m2_service)):
    """获取审核结果（读取本地审核报告）"""
    return service.get_audit_results()


@router.get("/pending-human", response_model=PendingHumanResponse)
def get_pending_human(service: M2Service = Depends(get_m2_service)):
    """获取等待人工终审的单"""
    return service.get_pending_human()


@router.post(
    "/human-gate/run/{run_id}/resume", response_model=HumanGateResumeResponse,
    responses=error_responses(400, 404, 409, 500),
)
def human_gate_resume_run(run_id: str, req: HumanGateResume, service: M2Service = Depends(get_m2_service)):
    """Resume a durable LangGraph human gate by immutable workflow run id."""
    try:
        return service.resume_human_gate(run_id, req)
    except ValueError as exc:
        if "不存在" in str(exc):
            raise api_error(404, "WORKFLOW_RUN_NOT_FOUND", str(exc)) from exc
        elif "冲突" in str(exc) or "版本" in str(exc) or "状态" in str(exc):
            raise api_error(409, "WORKFLOW_REVISION_CONFLICT", str(exc)) from exc
        else:
            raise api_error(400, "INVALID_HUMAN_DECISION", str(exc)) from exc
    except Exception as exc:
        logger.exception("Human gate resume failed run_id=%s", run_id)
        raise api_error(500, "WORKFLOW_RESUME_FAILED", "人工终审恢复失败，请使用 requestId 查询日志") from exc


@router.post(
    "/human-gate/{claim_id}/resume", response_model=HumanGateResumeResponse, deprecated=True,
    responses=error_responses(400, 404, 409, 500),
)
def human_gate_resume_claim(claim_id: str, req: HumanGateResume, service: M2Service = Depends(get_m2_service)):
    """2.0 compatibility route; new clients must submit workflowRunId instead."""
    try:
        return service.resume_human_gate_by_claim(claim_id, req)
    except ValueError as exc:
        if "不存在" in str(exc) or "没有" in str(exc):
            raise api_error(404, "WORKFLOW_RUN_NOT_FOUND", str(exc)) from exc
        elif "冲突" in str(exc) or "版本" in str(exc):
            raise api_error(409, "WORKFLOW_REVISION_CONFLICT", str(exc)) from exc
        else:
            raise api_error(400, "INVALID_HUMAN_DECISION", str(exc)) from exc
    except Exception as exc:
        logger.exception("Human gate resume failed claim_id=%s", claim_id)
        raise api_error(500, "WORKFLOW_RESUME_FAILED", "人工终审恢复失败，请使用 requestId 查询日志") from exc
