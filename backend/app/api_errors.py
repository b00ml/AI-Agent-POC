"""Error envelope helpers and exception handlers for the FastAPI application."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.schemas.common import ErrorResponse

logger = logging.getLogger("api")


def request_id_for(request: Request) -> str:
    """Return the request id established by middleware, or create one for errors."""
    request_id = getattr(request.state, "request_id", None)
    if not request_id:
        request_id = f"req_{uuid.uuid4().hex[:16]}"
        request.state.request_id = request_id
    return request_id


def api_error(status_code: int, code: str, message: str, details: Dict[str, Any] | None = None) -> HTTPException:
    """Create an HTTPException that the global handler serializes consistently."""
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, "details": details or {}},
    )


def error_responses(*status_codes: int) -> Dict[int, Dict[str, Any]]:
    """Add the shared error shape to OpenAPI for explicitly handled route errors."""
    return {status: {"model": ErrorResponse} for status in status_codes}


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Convert legacy string detail and structured detail into the same response envelope."""
    request_id = request_id_for(request)
    detail = exc.detail
    if isinstance(detail, dict) and {"code", "message"}.issubset(detail):
        code = str(detail["code"])
        message = str(detail["message"])
        details = detail.get("details") if isinstance(detail.get("details"), dict) else {}
    else:
        code = f"HTTP_{exc.status_code}"
        message = str(detail)
        details = {}
    body = ErrorResponse(code=code, message=message, requestId=request_id, details=details)
    return JSONResponse(status_code=exc.status_code, content=body.model_dump())


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Expose field validation failures without leaking arbitrary exception details."""
    request_id = request_id_for(request)
    body = ErrorResponse(
        code="VALIDATION_ERROR",
        message="请求参数不符合接口契约",
        requestId=request_id,
        details={"errors": exc.errors()},
    )
    return JSONResponse(status_code=422, content=body.model_dump())


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Do not return raw internal exception text to callers."""
    request_id = request_id_for(request)
    logger.exception("Unhandled API exception request_id=%s", request_id, exc_info=exc)
    body = ErrorResponse(
        code="INTERNAL_ERROR",
        message="服务内部错误，请使用 requestId 查询日志",
        requestId=request_id,
    )
    return JSONResponse(status_code=500, content=body.model_dump())
