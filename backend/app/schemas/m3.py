"""
M3 异常检测 Schema 定义
"""
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import ArtifactReference


# ==================== Request Models ====================

class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScanRequest(RequestModel):
    """异常扫描请求"""
    apiUrl: str = Field(default="", max_length=500, description="ERP API 地址")
    apiKey: str = Field(default="", max_length=2048, description="API Key")
    scope: Literal["all"] = Field(default="all", description="扫描范围")
    limit: Optional[int] = Field(default=None, ge=1, le=10000, description="限制扫描数量")
    useCached: bool = Field(default=False, description="是否使用缓存台账")


class AIReviewRequest(RequestModel):
    """AI 复核请求"""
    apiUrl: str = Field(default="", max_length=500, description="ERP API 地址")
    apiKey: str = Field(default="", max_length=2048, description="API Key")
    scope: Literal["all", "issues", "duplicates"] = Field(default="all", description="复核范围")
    useCached: bool = Field(default=False, description="是否使用缓存台账")


class AIScanRequest(RequestModel):
    """AI 批量巡检请求"""
    apiUrl: str = Field(default="", max_length=500, description="ERP API 地址")
    apiKey: str = Field(default="", max_length=2048, description="API Key")
    scope: Literal["all"] = Field(default="all", description="巡检范围")
    limit: Optional[int] = Field(default=None, ge=1, le=10000, description="巡检数量限制")
    batchSize: int = Field(default=60, ge=1, le=200, description="每批发票数")
    useCached: bool = Field(default=False, description="是否使用缓存台账")


# ==================== Response Models ====================

class JobCreatedResponse(BaseModel):
    """任务创建响应"""
    jobId: str
    status: str = "queued"
    message: str = ""


class JobStatusResponse(BaseModel):
    """任务状态响应"""
    jobId: str
    name: str
    status: str
    total: int = 0
    processed: int = 0
    phase: str = ""
    results: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    cancelRequested: bool = False
    createdAt: str
    updatedAt: str


class InvoiceDetail(BaseModel):
    """发票明细"""
    invoiceCode: Optional[str] = None
    invoiceNo: Optional[str] = None
    invoiceKind: Optional[str] = None
    issuedOn: Optional[str] = None
    buyerName: Optional[str] = None
    buyerTaxNo: Optional[str] = None
    sellerName: Optional[str] = None
    taxRate: Optional[float] = None
    totalFen: Optional[int] = None


class DuplicateAnomaly(BaseModel):
    """重复报销异常"""
    type: str = "重复报销"
    invoiceCode: Optional[str] = None
    invoiceNo: Optional[str] = None
    claimIds: List[str] = Field(default_factory=list)
    basis: str = ""
    invoices: List[Dict[str, Any]] = Field(default_factory=list)


class IssueAnomaly(BaseModel):
    """发票问题异常"""
    type: str
    invoiceId: Optional[str] = None
    basis: str = ""
    invoice: InvoiceDetail


class ScanResultsResponse(BaseModel):
    """M3 scan result; names match the historical frontend contract."""

    duplicateInvoices: List[Dict[str, Any]] = Field(default_factory=list)
    invoiceIssues: List[Dict[str, Any]] = Field(default_factory=list)
    supplierProfiles: List[Dict[str, Any]] = Field(default_factory=list)
    fromCache: bool = False
    message: Optional[str] = None
    artifact: Optional[ArtifactReference] = None


class AIReviewResultsResponse(BaseModel):
    """M3 AI review result, including its immutable artifact reference."""

    generatedAt: Optional[str] = None
    model: Optional[str] = None
    skill: Optional[str] = None
    scope: Optional[str] = None
    total: int = 0
    failed: int = 0
    results: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    fromCache: bool = False
    message: Optional[str] = None
    artifact: Optional[ArtifactReference] = None


class AIScanResultsResponse(BaseModel):
    """M3 AI scan result, keeping current dashboard field names stable."""

    generatedAt: Optional[str] = None
    totalInvoices: int = 0
    batchCount: int = 0
    flaggedCount: int = 0
    results: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    flagged: List[Dict[str, Any]] = Field(default_factory=list)
    fromCache: bool = False
    message: Optional[str] = None
    artifact: Optional[ArtifactReference] = None
