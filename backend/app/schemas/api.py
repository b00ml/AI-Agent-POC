"""
Pydantic 通用数据模型
"""
from pydantic import BaseModel
from typing import Optional, Any


class ApiResponse(BaseModel):
    """通用 API 响应"""
    status: str = "ok"
    message: Optional[str] = None
    data: Optional[Any] = None


class Pagination(BaseModel):
    """分页参数"""
    page: int = 1
    pageSize: int = 20
    total: int = 0
