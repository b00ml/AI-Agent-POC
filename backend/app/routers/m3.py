"""
M3 异常检测路由（重构版，逻辑移至 M3Service）
"""
import logging

from fastapi import APIRouter, Depends

from app.api_errors import api_error, error_responses
from app.jobs import JobQueueFull
from app.schemas.m3 import (
    ScanRequest,
    AIReviewRequest,
    AIScanRequest,
    JobCreatedResponse,
    JobStatusResponse,
    AIReviewResultsResponse,
    AIScanResultsResponse,
    ScanResultsResponse,
)
from app.services import get_m3_service
from app.services.m3_service import M3Service

router = APIRouter()
logger = logging.getLogger("api.m3")


@router.post("/scan", response_model=ScanResultsResponse, responses=error_responses(422, 500))
def scan_anomalies(
    req: ScanRequest,
    service: M3Service = Depends(get_m3_service)
):
    """执行 M3 全量发票异常检测"""
    try:
        return service.scan_anomalies(req)
    except Exception as exc:
        logger.exception("M3 scan failed")
        raise api_error(500, "M3_SCAN_FAILED", "M3 扫描失败，请使用 requestId 查询日志") from exc


@router.get("/results", response_model=ScanResultsResponse)
def get_anomaly_results(service: M3Service = Depends(get_m3_service)):
    """获取最近一次异常检测结果"""
    return service.get_scan_results()


@router.post("/ai-review", response_model=JobCreatedResponse, status_code=202, responses=error_responses(422, 503))
def ai_review_anomalies(
    req: AIReviewRequest,
    service: M3Service = Depends(get_m3_service)
):
    """启动 AI 复核异步任务"""
    try:
        return service.start_ai_review(req)
    except JobQueueFull as exc:
        raise api_error(503, "JOB_QUEUE_FULL", str(exc)) from exc


@router.get("/ai-review-status/{job_id}", response_model=JobStatusResponse, responses=error_responses(404))
def ai_review_status(
    job_id: str,
    service: M3Service = Depends(get_m3_service)
):
    """查询 AI 复核任务进度"""
    job = service.get_ai_review_status(job_id)
    if not job:
        raise api_error(404, "JOB_NOT_FOUND", "任务不存在或已过期")
    return job


@router.get("/ai-review-results", response_model=AIReviewResultsResponse)
def get_ai_review_results(service: M3Service = Depends(get_m3_service)):
    """获取最近一次 AI 复核结果"""
    return service.get_ai_review_results()


@router.post("/ai-scan", response_model=JobCreatedResponse, status_code=202, responses=error_responses(422, 503))
def ai_scan_invoices(
    req: AIScanRequest,
    service: M3Service = Depends(get_m3_service)
):
    """启动 AI 全量巡检异步任务"""
    try:
        return service.start_ai_scan(req)
    except JobQueueFull as exc:
        raise api_error(503, "JOB_QUEUE_FULL", str(exc)) from exc


@router.get("/ai-scan-status/{job_id}", response_model=JobStatusResponse, responses=error_responses(404))
def ai_scan_status(
    job_id: str,
    service: M3Service = Depends(get_m3_service)
):
    """查询 AI 全量巡检任务进度"""
    job = service.get_ai_scan_status(job_id)
    if not job:
        raise api_error(404, "JOB_NOT_FOUND", "任务不存在或已过期")
    return job


@router.get("/ai-scan-results", response_model=AIScanResultsResponse)
def get_ai_scan_results(service: M3Service = Depends(get_m3_service)):
    """获取最近一次 AI 全量巡检结果"""
    return service.get_ai_scan_results()
