"""
M2 审核相关的 Request/Response 模型
"""
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# ============ Request Models ============

class RequestModel(BaseModel):
    """Base for externally supplied command payloads."""

    model_config = ConfigDict(extra="forbid")


class AuditRequest(RequestModel):
    """M2 审核请求"""
    claimIds: List[str] = Field(min_length=1, max_length=300)
    apiUrl: str = Field(default="", max_length=500)
    apiKey: str = Field(default="", max_length=2048)
    writeBack: bool = False


class OCRRequest(RequestModel):
    """OCR 识别请求"""
    claimId: str = Field(min_length=1, max_length=128)
    apiUrl: str = Field(default="", max_length=500)
    apiKey: str = Field(default="", max_length=2048)


class ReviewRequest(RequestModel):
    """人工复核请求"""
    claimId: str = Field(min_length=1, max_length=128)
    decision: Literal["APPROVE", "REJECT", "FLAG"]
    comment: Optional[str] = Field(default=None, max_length=2000)
    evidence: List[Dict[str, Any]] = Field(default_factory=list)
    aiResult: Optional[Literal["APPROVE", "REJECT", "FLAG"]] = None
    aiViolations: List[str] = Field(default_factory=list)
    aiReasons: List[str] = Field(default_factory=list)
    aiConfidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    apiUrl: str = Field(default="", max_length=500)
    apiKey: str = Field(default="", max_length=2048)


class HumanGateResume(RequestModel):
    """人工终审恢复请求"""
    decision: Literal["APPROVE", "REJECT", "FLAG"]
    comment: Optional[str] = Field(default="", max_length=2000)
    expectedRevision: int = Field(ge=0)
    apiUrl: str = Field(default="", max_length=500)
    apiKey: str = Field(default="", max_length=2048)


# ============ Response Models ============

class JobCreatedResponse(BaseModel):
    """任务创建响应"""
    jobId: str
    status: str = "queued"


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


class JobCancelResponse(BaseModel):
    """任务取消响应"""
    jobId: str
    status: str
    cancelRequested: bool


class OCRResponse(BaseModel):
    """OCR 识别响应"""
    claimId: str
    invoices: List[Dict[str, Any]]
    totalAmount: float = 0.0
    count: int = 0


class ReviewResponse(BaseModel):
    """人工复核响应"""
    status: str
    claimId: str
    result: Any


class AuditResultItem(BaseModel):
    """单条审核结果"""
    claimId: str
    result: str
    reasons: List[str] = Field(default_factory=list)
    violations: List[str] = Field(default_factory=list)
    confidence: Optional[float] = None
    decisionStrength: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    aiReview: Optional[Dict[str, Any]] = None
    writtenBack: bool = False
    updatedAt: Optional[str] = None


class AuditResultsResponse(BaseModel):
    """审核结果列表响应"""
    total: int
    results: List[AuditResultItem]


class PendingHumanItem(BaseModel):
    """待人工终审单据"""
    claimId: str
    workflowRunId: str
    revision: int
    ruleResult: str
    aiReview: Optional[Dict[str, Any]] = None
    createdAt: str


class PendingHumanResponse(BaseModel):
    """待人工终审列表响应"""
    count: int
    pending: List[PendingHumanItem]


class HumanGateResumeResponse(BaseModel):
    """人工终审完成响应"""
    status: str
    claimId: str
    workflowRunId: str
    finalResult: str
