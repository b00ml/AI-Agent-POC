"""
submission.json 生成器（符合官方校验器 validate-submission.mjs 的 v1 格式）

格式：
{
  "version": 1,
  "meta": { team, members, seed, submittedAt, repoUrl, aiModels, dataEgress, apiScopes },
  "m2": { "reviews": [ { claimId, result, violations, reasons, confidence } ] },
  "m3": { "duplicateInvoices": [...], "invoiceIssues": [...] },
  "m4": { "matches": [...], "unidentified": [...] },
  "eval": { "extractionAccuracy": 0.x, "testSetSize": 30, "notes": "..." }
}
"""

import os
import json
import time
from typing import Optional, List, Dict, Any

from core.auditor import AuditResult
from data.config import SUBMISSION_FILE
from core.logger import get_logger

logger = get_logger("submission")


_OFFICIAL_M3_ISSUES = {"TITLE_WRONG", "TAXNO_WRONG", "TAX_RATE_WRONG"}
_OFFICIAL_M2_VIOLATIONS = {
    "OVER_STANDARD_HOTEL", "OVER_STANDARD_MEAL", "OVER_STANDARD_CITY_TRANSPORT",
    "OVER_STANDARD_TRANSPORT_CLASS", "INVOICE_TITLE_MISMATCH", "INVOICE_TAXNO_MISMATCH",
    "DUPLICATE_INVOICE", "MISSING_APPROVAL_OVERTIME_TAXI", "MISSING_ATTACHMENT",
    "AMOUNT_MISMATCH",
}


def _sanitize_m2_review(review: AuditResult) -> dict:
    """把引擎结果映射为官方提交口径：
    - result 三值 APPROVE/REJECT/**FLAG** 原样保留（FLAG 是官方允许的第三取值，不转换）；
    - violations 只保留官方 10 码（扩展码如 ACCOUNT_MISMATCH 不在官方格式内，去掉）；
    - 若仅因扩展码被判 REJECT，官方口径下视为无官方违规（APPROVE），并保留说明。
    """
    violations = [v.code for v in review.violations if v.code in _OFFICIAL_M2_VIOLATIONS]
    result = review.result
    if result == "REJECT" and not violations and review.violations:
        result = "APPROVE"
    reasons = review.reasons or []
    if result == "APPROVE" and not violations and review.violations:
        reasons = ["仅命中扩展规则（如科目归集校验），官方违规码为空"] + reasons
    return {
        "claimId": review.claim_id,
        "result": result,
        "violations": violations,
        "reasons": reasons,
        # 官方 v1 仍要求 confidence；其值来自规则决策强度，不宣称为概率。
        "confidence": round(review.decision_strength, 2),
    }


def _sanitize_m3(m3_result: Dict[str, Any]) -> Dict[str, Any]:
    """按官方提交口径净化 m3：仅保留官方 3 类票面问题、去掉疑似重复（避免误报扣分）"""
    if not m3_result:
        return {"duplicateInvoices": [], "invoiceIssues": []}
    dups = []
    for d in m3_result.get("duplicateInvoices", []):
        if d.get("suspected"):
            continue
        dups.append({
            "invoiceCode": d.get("invoiceCode"),
            "invoiceNo": d.get("invoiceNo"),
            "claimIds": sorted(set(d.get("claimIds") or [])),
        })
    issues = [
        {"invoiceId": i.get("invoiceId"), "issue": i.get("issue")}
        for i in m3_result.get("invoiceIssues", [])
        if i.get("issue") in _OFFICIAL_M3_ISSUES
    ]
    return {"duplicateInvoices": dups, "invoiceIssues": issues}


def _sanitize_m4(m4_result: Dict[str, Any]) -> Dict[str, Any]:
    """按官方提交口径净化 m4：matches 只保留 txnId+receivableIds；unidentified 为 txnId 数组"""
    if not m4_result:
        return {}
    matches = [
        {"txnId": m.get("txnId"), "receivableIds": m.get("receivableIds", [])}
        for m in m4_result.get("matches", [])
        if m.get("txnId")
    ]
    unidentified = []
    for u in m4_result.get("unidentified", []):
        if isinstance(u, dict):
            if u.get("txnId"):
                unidentified.append(u["txnId"])
        elif isinstance(u, str):
            unidentified.append(u)
    return {"matches": matches, "unidentified": unidentified}


class SubmissionGenerator:
    """submission.json 生成器"""

    def __init__(self) -> None:
        self.meta = {
            "team": "启衡AI财务提效小组",
            "members": ["FDE-001"],
            "seed": "qiheng-2026-v1",
            "submittedAt": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            "repoUrl": "",
            "aiModels": [
                {
                    "provider": "阿里云百炼（DashScope）",
                    "model": "qwen3.6-flash",
                    "purpose": "发票票据影像票面要素抽取（购方抬头/税号/金额/税率）",
                }
            ],
            "dataEgress": [
                {
                    "field": "发票图片（base64 编码的票据影像）",
                    "sentTo": "阿里云百炼 qwen3.6-flash（多模态）",
                    "reason": "OCR 提取票面要素，以票面为准进行合规判定",
                }
            ],
            "apiScopes": [
                "master-data:read",
                "expense:read",
                "expense:review",
                "approval:read",
                "attachment:read",
                "invoice:read",
                "receivable:read",
            ],
        }

    def build_full_submission(
        self,
        m2_results: List[AuditResult],
        m3_result: Dict[str, Any],
        eval_result: Optional[Dict[str, Any]] = None,
        m4_result: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """构建完整 submission（v1 格式）"""

        m2_reviews = [_sanitize_m2_review(r) for r in m2_results]

        submission: Dict[str, Any] = {
            "version": 1,
            "meta": self.meta,
            "m2": {"reviews": m2_reviews},
            "m3": _sanitize_m3(m3_result),
        }

        if m4_result:
            submission["m4"] = _sanitize_m4(m4_result)

        if eval_result:
            submission["eval"] = {
                "extractionAccuracy": eval_result.get("extractionAccuracy", 0.0),
                "testSetSize": eval_result.get("testSetSize", 30),
                "notes": eval_result.get("notes", ""),
            }

        return submission

    def save(
        self,
        submission: Dict[str, Any],
        filepath: Optional[str] = None,
    ) -> str:
        """保存 submission.json"""
        filepath = filepath or SUBMISSION_FILE
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(submission, f, ensure_ascii=False, indent=2)
        logger.info(f"✓ submission.json 已生成: {filepath}")
        return filepath

    def validate(self, filepath: Optional[str] = None) -> List[str]:
        """
        本地格式自检（与官方校验器同口径）。
        返回错误信息列表；为空表示通过。
        """
        filepath = filepath or SUBMISSION_FILE
        errors: List[str] = []

        if not os.path.exists(filepath):
            return [f"文件不存在: {filepath}"]

        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        if data.get("version") != 1:
            errors.append("version 必须为 1")
        if not data.get("meta") or not data["meta"].get("team"):
            errors.append("meta.team 缺失")
        if not data["meta"].get("members"):
            errors.append("meta.members 缺失")
        if data["meta"].get("seed") != "qiheng-2026-v1":
            errors.append("meta.seed 必须为 qiheng-2026-v1")

        reviews = (data.get("m2") or {}).get("reviews")
        if not isinstance(reviews, list) or len(reviews) == 0:
            errors.append("m2.reviews 缺失或为空")
        else:
            seen = set()
            for i, r in enumerate(reviews):
                if not r.get("claimId"):
                    errors.append(f"m2.reviews[{i}].claimId 缺失")
                elif r["claimId"] in seen:
                    errors.append(f"m2.reviews[{i}].claimId 重复")
                else:
                    seen.add(r["claimId"])
                if r.get("result") not in ("APPROVE", "REJECT", "FLAG"):
                    errors.append(f"m2.reviews[{i}].result 非法: {r.get('result')}")
                if not isinstance(r.get("violations"), list):
                    errors.append(f"m2.reviews[{i}].violations 必须为数组")

        return errors
