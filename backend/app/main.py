"""
启衡精密 AI 财务审核 - FastAPI 后端
"""
import sys
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from dotenv import load_dotenv

load_dotenv()

# 复用现有核心逻辑（项目根目录入 path，统一 from core.xxx 导入）
REPO_ROOT = Path(__file__).parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.routers import erp, m2, m3, m4, settings
from app.api_errors import (
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)

app = FastAPI(
    title="启衡精密 AI 财务审核 API",
    description="企业级财务审核系统后端 API",
    version="2.0.0",
)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Attach a traceable request id to normal and error responses."""
    request.state.request_id = request.headers.get("X-Request-ID") or f"req_{uuid.uuid4().hex[:16]}"
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

# 注册路由
app.include_router(erp.router, prefix="/api/erp", tags=["ERP"])
app.include_router(m2.router, prefix="/api/m2", tags=["M2 合规审核"])
app.include_router(m3.router, prefix="/api/m3", tags=["M3 异常检测"])
app.include_router(m4.router, prefix="/api/m4", tags=["M4 银行对账"])
app.include_router(settings.router, prefix="/api/settings", tags=["系统设置"])

@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "version": "2.0.0"}
