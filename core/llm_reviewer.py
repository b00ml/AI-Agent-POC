"""
AI 复核助手（LLM 双轨复核）

规则引擎给出初审结论与证据后，本模块让大模型独立复核同一份证据，
输出自己的结论；与规则结论不一致时，提示提请人工复核（FLAG）。

 设计约束：
- LLM 只给意见，不改变单据状态
- 默认启用（配置 API Key 即默认开启；可在设置页关闭，避免外发数据）
- 模型服务与出域字段需在 submission.meta.dataEgress 申报
"""

import os
import json
from typing import Dict, Any, List

from dotenv import load_dotenv

from core.logger import get_logger
from core.llm_client import LLMClient
from core.retrieval import PolicyRetriever, format_clauses
from data.config import DEFAULT_CITY_TIERS

load_dotenv()
logger = get_logger("llm_reviewer")

M2_RESULTS = {"APPROVE", "REJECT", "FLAG"}
M2_VIOLATIONS = {
    "OVER_STANDARD_HOTEL", "OVER_STANDARD_MEAL", "OVER_STANDARD_CITY_TRANSPORT",
    "OVER_STANDARD_TRANSPORT_CLASS", "INVOICE_TITLE_MISMATCH", "INVOICE_TAXNO_MISMATCH",
    "DUPLICATE_INVOICE", "MISSING_APPROVAL_OVERTIME_TAXI", "MISSING_ATTACHMENT",
    "AMOUNT_MISMATCH", "ACCOUNT_MISMATCH",
}
M3_VERDICTS = {"CONFIRM", "DOUBT", "FALSE_ALARM"}

# 单据特征 → 检索查询词（dense 检索的自然语言场景描述用）
_EXPENSE_TYPE_QUERY_LABEL = {
    "HOTEL": "住宿费", "MEAL": "伙食补助", "CITY_TRANSPORT": "市内交通",
    "LONG_TRANSPORT": "长途交通", "TAXI": "打车", "ENTERTAIN": "业务招待",
}
_VIOLATION_QUERY_LABEL = {
    "OVER_STANDARD_HOTEL": "住宿费超标",
    "OVER_STANDARD_MEAL": "伙食补助超标",
    "OVER_STANDARD_CITY_TRANSPORT": "市内交通超标",
    "OVER_STANDARD_TRANSPORT_CLASS": "长途舱位超标",
    "INVOICE_TITLE_MISMATCH": "发票抬头不符",
    "INVOICE_TAXNO_MISMATCH": "购方税号不符",
    "DUPLICATE_INVOICE": "重复报销",
    "MISSING_APPROVAL_OVERTIME_TAXI": "加班打车缺事前审批",
    "MISSING_ATTACHMENT": "缺少票据附件",
    "AMOUNT_MISMATCH": "报销金额与票面不一致",
    "ACCOUNT_MISMATCH": "差旅科目归集错误",
}


def is_llm_review_enabled() -> bool:
    """AI 复核是否开启：显式设置过 LLM_REVIEW_ENABLED 时以设置为准；
    未显式设置时，默认开启（前提是已配置模型 API Key）。"""
    val = os.environ.get("LLM_REVIEW_ENABLED")
    if val is not None:
        return val == "1"
    return bool(os.environ.get("LLM_REVIEW_API_KEY") or os.environ.get("DASHSCOPE_API_KEY"))


def _valid_m2_review(parsed: dict) -> bool:
    return (
        parsed.get("result") in M2_RESULTS
        and isinstance(parsed.get("violations"), list)
        and all(v in M2_VIOLATIONS for v in parsed.get("violations", []))
        and isinstance(parsed.get("reasons"), list)
        and isinstance(parsed.get("confidence"), (int, float))
        and 0 <= parsed.get("confidence", 0) <= 1
    )


def _valid_m3_review(parsed: dict) -> bool:
    return (
        parsed.get("verdict") in M3_VERDICTS
        and isinstance(parsed.get("reasons"), list)
        and isinstance(parsed.get("confidence"), (int, float))
        and 0 <= parsed.get("confidence", 0) <= 1
    )


def _load_prompt() -> str:
    prompt_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "data", "prompts", "llm_review.txt",
    )
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read()


REVIEW_PROMPT_TEMPLATE = _load_prompt()


def _load_m2_claim_review_skill() -> str:
    """加载业务环节 Skill（doc/skills/m2-claim-review/SKILL.md）：
    运行时把该 Skill 内容注入 DeepSeek 提示词，作为 M2 AI 复核环节的执行工作流。
    """
    skill_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "doc", "skills", "m2-claim-review", "SKILL.md",
    )
    with open(skill_path, "r", encoding="utf-8") as f:
        return f.read()


M2_CLAIM_REVIEW_SKILL = _load_m2_claim_review_skill()


def _load_m3_ai_review_prompt() -> str:
    prompt_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "data", "prompts", "m3_ai_review.txt",
    )
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read()


M3_AI_REVIEW_PROMPT_TEMPLATE = _load_m3_ai_review_prompt()


def _load_m3_ai_review_skill() -> str:
    """加载业务环节 Skill（doc/skills/m3-ai-review/SKILL.md）：
    运行时把该 Skill 内容注入 DeepSeek 提示词，作为 AI 复核环节的执行工作流。
    """
    skill_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "doc", "skills", "m3-ai-review", "SKILL.md",
    )
    with open(skill_path, "r", encoding="utf-8") as f:
        return f.read()


M3_AI_REVIEW_SKILL = _load_m3_ai_review_skill()


def _load_policy_kb() -> List[dict]:
    """加载制度知识库（data/rag_index/index.json，条款级分块）"""
    kb_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "data", "rag_index", "index.json",
    )
    if not os.path.exists(kb_path):
        return []
    with open(kb_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("chunks", [])


class LLMReviewer:
    """大模型独立复核助手（OpenAI 兼容接口，默认阿里云百炼千问）"""

    def __init__(self) -> None:
        # 默认 DeepSeek V4 Flash；也可通过 LLM_REVIEW_* 覆盖（OpenAI 兼容接口）
        api_key = os.getenv("LLM_REVIEW_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
        if not api_key:
            raise ValueError("未配置 LLM_REVIEW_API_KEY / DASHSCOPE_API_KEY，无法启用 AI 复核助手")
        base_url = os.getenv(
            "LLM_REVIEW_BASE_URL",
            os.getenv("DASHSCOPE_BASE_URL", "https://api.deepseek.com/v1"),
        )
        self.model = os.getenv(
            "LLM_REVIEW_MODEL",
            os.getenv("QWEN_REVIEW_MODEL", "deepseek-v4-flash"),
        )
        self.client = LLMClient(
            api_key=api_key, base_url=base_url, model=self.model,
            max_retries=3, timeout=90,
        )
        self.call_count = 0
        self.retriever = PolicyRetriever()
        self._policy_kb = self.retriever.chunks
        logger.info(
            "制度知识库加载完成: %d 条条款（检索模式 %s）",
            len(self._policy_kb), self.retriever.mode,
        )

    def review_claim(
        self,
        claim_detail: dict,
        approvals: List[dict],
        travel_standards: List[dict],
        ocr_fields: Dict[str, dict],
        rules_opinion: Dict[str, Any],
    ) -> Dict[str, Any]:
        """对单个报销单做独立复核"""
        prompt = self._build_prompt(claim_detail, approvals, travel_standards, ocr_fields, rules_opinion)
        parsed = self.client.chat_json(
            prompt,
            validator=_valid_m2_review,
            trace_id=claim_detail.get("id", ""),
        )
        if not parsed:
            return {"error": "解析/校验失败"}

        result = parsed.get("result", "")
        agree = (result == rules_opinion.get("result"))
        parsed["agreeWithRules"] = agree
        return parsed

    def review_m3_anomaly(self, anomaly: dict, keywords: set) -> Dict[str, Any]:
        """复核单条 M3 异常（发票异常是否成立）"""
        query_text = f"{anomaly.get('issue', '')} {anomaly.get('basis', '')}".strip()
        prompt = M3_AI_REVIEW_PROMPT_TEMPLATE.format(
            skill_content=M3_AI_REVIEW_SKILL,
            anomaly=json.dumps(anomaly, ensure_ascii=False, indent=1),
            policy_clauses=format_clauses(
                self.retriever.retrieve(query_text=query_text, keywords=keywords, top_k=8)
            ),
        )
        parsed = self.client.chat_json(
            prompt,
            validator=_valid_m3_review,
            trace_id=anomaly.get("invoiceId") or anomaly.get("invoiceNo") or "",
        )
        if not parsed:
            return {"error": "解析/校验失败"}
        return parsed

    def _build_prompt(
        self,
        claim_detail: dict,
        approvals: List[dict],
        travel_standards: List[dict],
        ocr_fields: Dict[str, dict],
        rules_opinion: Dict[str, Any],
    ) -> str:
        trip = claim_detail.get("trip") or {}

        lines = []
        for ln in claim_detail.get("lines", []):
            inv = ln.get("invoice") or {}
            buyer = inv.get("buyer") or {}
            seller = inv.get("seller") or {}
            att = ln.get("attachment") or {}
            lines.append(
                f"- 行{ln.get('lineNo')} {ln.get('expenseType')} {ln.get('description')} "
                f"金额{ln.get('amountFen', 0) / 100:.2f}元 "
                f"发票代码/号码：{inv.get('invoiceCode', '')}/{inv.get('invoiceNo', '')} "
                f"系统购方：{buyer.get('name', '')} 税号：{buyer.get('taxNo', '')} "
                f"销方：{seller.get('name', '')}"
            )

        std_lines = []
        for std in travel_standards:
            std_lines.append(
                f"- {std.get('jobLevel')} {std.get('cityTier')}: "
                f"住宿{std.get('hotelCapPerNightFen', 0) / 100:.0f}元/晚 "
                f"伙食{std.get('mealAllowancePerDayFen', 0) / 100:.0f}元/天 "
                f"市内交通{std.get('cityTransportPerDayFen', 0) / 100:.0f}元/天 "
                f"长途{std.get('longDistanceClass', '')}"
            )

        ap_lines = []
        for a in approvals or []:
            ap_lines.append(
                f"- {a.get('action')} 审批人:{a.get('approverName', '')} "
                f"备注:{a.get('comment') or ''}"
            )

        ocr_lines = []
        for ln in claim_detail.get("lines", []):
            att = ln.get("attachment") or {}
            if not att:
                continue
            f = ocr_fields.get(att.get("id"), {})
            if f:
                ocr_lines.append(
                    f"- 附件{att.get('id')}（行{ln.get('lineNo')}）OCR购方:{f.get('buyerName') or '（无）'} "
                    f"OCR税号:{f.get('buyerTaxNo') or '（无）'} OCR金额:{f.get('totalAmount') or '（无）'}"
                )

        opinion = {
            "result": rules_opinion.get("result"),
            "violations": rules_opinion.get("violations", []),
            "reasons": rules_opinion.get("reasons", []),
        }

        policy_clauses = self._retrieve_clauses(claim_detail, rules_opinion)

        # 出差城市档次映射（直接随单据给出，避免依赖检索命中）
        tier_lines = [f"- {city}：{tier}" for city, tier in DEFAULT_CITY_TIERS.items()]
        trip_city = trip.get("city", "")
        city_tiers = "\n".join(tier_lines)
        if trip_city:
            current_tier = next(
                (tier for city, tier in DEFAULT_CITY_TIERS.items()
                 if city in trip_city or trip_city in city),
                "",
            )
            city_tiers += f"\n- 当前单据出差城市：{trip_city} → {current_tier or '未收录'}"

        return REVIEW_PROMPT_TEMPLATE.format(
            claim_no=claim_detail.get("claimNo", claim_detail.get("id", "")),
            job_level=claim_detail.get("jobLevel", ""),
            department=claim_detail.get("departmentName", ""),
            claim_type=claim_detail.get("claimType", ""),
            city=trip.get("city", "（无）"),
            nights=trip.get("nights", 0),
            lines="\n".join(lines) or "（无费用行）",
            standards="\n".join(std_lines) or "（无标准）",
            approvals="\n".join(ap_lines) or "（无审批记录）",
            ocr_fields="\n".join(ocr_lines) or "（无 OCR 数据）",
            rules_opinion=json.dumps(opinion, ensure_ascii=False),
            policy_clauses=policy_clauses,
            skill_content=M2_CLAIM_REVIEW_SKILL,
            city_tiers=city_tiers,
        )

    def _retrieve_clauses(self, claim_detail: dict, rules_opinion: dict) -> str:
        """按单据特征检索知识库条款（hybrid：场景语义+关键词融合；keyword 模式下与 1.x 一致）"""
        keywords = self._claim_keywords(claim_detail, rules_opinion)
        query_text = self._build_query_text(claim_detail, rules_opinion)
        return format_clauses(
            self.retriever.retrieve(query_text=query_text, keywords=keywords, top_k=8)
        )

    def _build_query_text(self, claim_detail: dict, rules_opinion: dict) -> str:
        """把单据特征压成一句自然语言场景描述，作为 dense 检索查询"""
        parts = []
        trip = claim_detail.get("trip") or {}
        if isinstance(trip, dict) and trip.get("city"):
            parts.append(f"出差{trip['city']}")
        for ln in claim_detail.get("lines", []):
            et = ln.get("expenseType", "")
            label = _EXPENSE_TYPE_QUERY_LABEL.get(et, et)
            desc = (ln.get("description") or "").strip()
            parts.append(f"{label}（{desc}）" if desc else label)
        for v in rules_opinion.get("violations", []):
            parts.append(_VIOLATION_QUERY_LABEL.get(v, v))
        if rules_opinion.get("result") == "FLAG":
            parts.append("证据缺失需人工裁定")
        return "；".join(parts)

    def _claim_keywords(self, claim_detail: dict, rules_opinion: dict) -> set:
        keywords = set()
        for ln in claim_detail.get("lines", []):
            et = ln.get("expenseType", "")
            if et == "HOTEL":
                keywords.update(["住宿", "酒店", "每晚"])
            elif et == "MEAL":
                keywords.update(["伙食", "餐", "每天"])
            elif et == "CITY_TRANSPORT":
                keywords.update(["市内交通", "打车", "出租车", "加班"])
            elif et == "LONG_TRANSPORT":
                keywords.update(["长途", "舱位", "高铁", "机票"])
            desc = ln.get("description", "")
            if "加班" in desc:
                keywords.add("加班")
            if "业务招待" in desc or et == "ENTERTAIN":
                keywords.add("业务招待")
        for v in rules_opinion.get("violations", []):
            if "HOTEL" in v: keywords.update(["住宿", "每晚"])
            elif "MEAL" in v: keywords.update(["伙食"])
            elif "CITY_TRANSPORT" in v or "TAXI" in v: keywords.update(["市内交通", "打车", "加班"])
            elif "TRANSPORT_CLASS" in v: keywords.update(["长途", "舱位"])
            elif "TITLE" in v: keywords.update(["抬头", "发票"])
            elif "TAXNO" in v: keywords.update(["税号", "纳税人识别号"])
            elif "DUPLICATE" in v: keywords.update(["重复", "查重"])
            elif "APPROVAL" in v: keywords.update(["审批", "事前"])
            elif "ATTACHMENT" in v: keywords.update(["附件", "票据"])
            elif "AMOUNT" in v: keywords.update(["金额", "票面金额"])
        keywords.update(["特批", "事前审批", "以票面为准", "发票抬头", "税号"])
        return keywords

    def _retrieve_by_keywords(self, keywords: set) -> str:
        """兼容入口：仅按关键词检索（keyword 模式行为与 1.x 一致）"""
        return format_clauses(self.retriever.retrieve(keywords=keywords, top_k=8))

    def get_stats(self) -> Dict[str, int]:
        return dict(self.client.stats)
