"""
M4 银行对账 Schema 定义
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import ArtifactReference


# ==================== Request Models ====================

class ReconcileRequest(BaseModel):
    """银行对账请求"""
    model_config = ConfigDict(extra="forbid")

    apiUrl: str = Field(default="", max_length=500, description="ERP API 地址")
    apiKey: str = Field(default="", max_length=2048, description="M4 专用 API Key (receivable:read)")


# ==================== Response Models ====================

class ReconcileMatch(BaseModel):
    """对账匹配项"""
    txnId: str
    receivableIds: List[str] = Field(default_factory=list)
    amountFen: int
    note: str = ""


class ReconcileUnidentified(BaseModel):
    """未匹配银行流水"""
    txnId: str
    reason: str


class ReconcileStatistics(BaseModel):
    matched: int = 0
    unidentified: int = 0
    total: int = 0
    matchedRate: float = 0.0
    unidentifiedByReason: List[Dict[str, Any]] = Field(default_factory=list)
    parseErrors: List[Dict[str, Any]] = Field(default_factory=list)
    duplicateTxnIds: List[str] = Field(default_factory=list)


class ReconcileResultsResponse(BaseModel):
    """对账结果响应"""
    matches: List[ReconcileMatch] = Field(default_factory=list)
    unidentified: List[ReconcileUnidentified] = Field(default_factory=list)
    statistics: ReconcileStatistics = Field(default_factory=ReconcileStatistics)
    message: Optional[str] = None
    artifact: Optional[ArtifactReference] = None
