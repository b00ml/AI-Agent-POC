"""
AI 环节输出契约（pydantic，设计文档 2.0 §3.5）

替代手写 dict 校验：所有 LLM 结构化输出统一用 pydantic 模型定义与校验，
非法输出由 LLMClient 的修复重试机制回喂模型。
"""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

# ---- M2 复核 ----

M2_RESULTS = ("APPROVE", "REJECT", "FLAG")
OFFICIAL_M2_VIOLATIONS = (
    "OVER_STANDARD_HOTEL", "OVER_STANDARD_MEAL", "OVER_STANDARD_CITY_TRANSPORT",
    "OVER_STANDARD_TRANSPORT_CLASS", "INVOICE_TITLE_MISMATCH", "INVOICE_TAXNO_MISMATCH",
    "DUPLICATE_INVOICE", "MISSING_APPROVAL_OVERTIME_TAXI", "MISSING_ATTACHMENT",
    "AMOUNT_MISMATCH",
)
# 引擎扩展码（官方 10 码之外，submission 生成时剥离）
EXTENDED_M2_VIOLATIONS = ("ACCOUNT_MISMATCH",)
ALL_M2_VIOLATIONS = OFFICIAL_M2_VIOLATIONS + EXTENDED_M2_VIOLATIONS


class M2Review(BaseModel):
    result: Literal["APPROVE", "REJECT", "FLAG"]
    violations: List[str] = Field(default_factory=list)
    reasons: List[str]
    confidence: float = Field(ge=0.0, le=1.0)

    def normalized(self) -> "M2Review":
        """剥离不在违规码枚举内的幻觉码"""
        allowed = set(ALL_M2_VIOLATIONS)
        self.violations = [v for v in self.violations if v in allowed]
        return self


# ---- M3 复核 ----

M3_VERDICTS = ("CONFIRM", "DOUBT", "FALSE_ALARM")


class M3Review(BaseModel):
    verdict: Literal["CONFIRM", "DOUBT", "FALSE_ALARM"]
    reasons: List[str]
    confidence: float = Field(ge=0.0, le=1.0)


# ---- 调查 Agent ----

INVESTIGATION_CONCLUSIONS = (
    "maintain_rules",   # 维持规则结论
    "support_flag",     # 支持存疑，交人工
    "suggest_approve",  # 建议放行（与规则/复核意见不同）
    "suggest_reject",   # 建议驳回（与规则/复核意见不同）
)


class Evidence(BaseModel):
    """调查证据（M33 增强：source_id + field_path + call_id 三元组绑定）"""
    tool: str
    call_id: str
    finding: str
    ref: str = ""
    # M33 增强：证据来源绑定
    source_id: str = ""  # 工具返回的数据源ID（如 claim_id, attachment_id, clause_id）
    field_path: str = ""  # 数据字段路径（如 data.amount, clauses[0].content）
    grounded: Optional[bool] = None  # grounding 校验后回填


class InvestigationReport(BaseModel):
    """调查报告（M33 增强：降级原因追踪和成本统计）"""
    conclusion: Literal["maintain_rules", "support_flag", "suggest_approve", "suggest_reject"]
    evidence: List[Evidence] = Field(default_factory=list)
    summary: str
    confidence: float = Field(ge=0.0, le=1.0)
    # 以下为运行时回填字段，不由模型输出
    steps: int = 0
    tool_calls: int = 0
    tokens_used: int = 0
    degraded: bool = False
    degraded_reason: str = ""
    grounding_ok: Optional[bool] = None
    # M33 增强：成本和延迟统计
    total_cost: float = 0.0  # 美元
    wall_time_ms: int = 0
    grounding_failed_count: int = 0  # 未落地证据数量


def make_m2_validator():
    """chat_json 兼容 validator（闭包持有修复提示所需信息）"""

    def _validate(parsed: dict) -> bool:
        try:
            M2Review.model_validate(parsed)
            return True
        except Exception:
            return False

    return _validate


def make_m3_validator():
    def _validate(parsed: dict) -> bool:
        try:
            M3Review.model_validate(parsed)
            return True
        except Exception:
            return False

    return _validate
