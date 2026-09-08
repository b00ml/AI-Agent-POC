"""
M4 银行对账路由（重构版，逻辑移至 M4Service）
"""
import logging

from fastapi import APIRouter, Depends

from app.api_errors import api_error, error_responses
from app.schemas.m4 import ReconcileRequest, ReconcileResultsResponse
from app.services import get_m4_service
from app.services.m4_service import M4Service

router = APIRouter()
logger = logging.getLogger("api.m4")


@router.post("/reconcile", response_model=ReconcileResultsResponse, responses=error_responses(400, 422, 500))
def reconcile(
    req: ReconcileRequest,
    service: M4Service = Depends(get_m4_service)
):
    """执行银行对账"""
    try:
        return service.reconcile(req)
    except ValueError as exc:
        raise api_error(400, "M4_CONFIGURATION_INVALID", str(exc)) from exc
    except Exception as exc:
        logger.exception("M4 reconcile failed")
        raise api_error(500, "M4_RECONCILE_FAILED", "M4 对账失败，请使用 requestId 查询日志") from exc


@router.get("/results", response_model=ReconcileResultsResponse)
def get_reconcile_results(service: M4Service = Depends(get_m4_service)):
    """获取最近一次对账结果"""
    return service.get_reconcile_results()
