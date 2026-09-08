"""
LLM 复核链路冒烟测试：统一客户端（重试/校验）+ 知识库检索 + M2/M3 复核。
用法：python tools/smoke_llm_review.py
"""

import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

from core.client import QihengClient
from core.auditor import Auditor
from core.claim_store import load_invoice_index
from core.llm_reviewer import LLMReviewer
from data.travel_data import TravelDataManager


def main() -> None:
    client = QihengClient()
    tm = TravelDataManager(client)
    tm.load_data()
    auditor = Auditor(tm)
    auditor.set_invoice_index(load_invoice_index(client))
    reviewer = LLMReviewer()

    # 1. 知识库检索（税率关键词应命中发票合规指引税率表）
    kb = reviewer._retrieve_by_keywords({"税率", "适用", "增值税", "发票"})
    print("KB 检索命中率条款:", "税率" in kb and "13" in kb)
    print("KB 检索长度:", len(kb))

    # 2. M2 复核（1 单）
    detail = client.expense_claims_get("BX-005693")
    approvals = client.approvals_for_claim("BX-005693")
    audit = auditor.audit_claim(detail, approvals, ocr_results={})
    opinion = {
        "result": audit.result,
        "violations": [v.code for v in audit.violations],
        "reasons": audit.reasons,
    }
    out = reviewer.review_claim(detail, approvals, tm.list_standards(), {}, opinion)
    print("M2 复核:", out.get("result"), "| 校验通过:", "error" not in out, "| 与规则一致:", out.get("agreeWithRules"))

    # 3. M3 复核（税率异常 1 条，用台账记录）
    ledger = json.load(open(
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "output", "cache", "invoice_ledger.json"),
        encoding="utf-8",
    ))
    rate_issue = next(
        (inv for inv in ledger
         if inv.get("invoiceKind") == "VAT_GENERAL" and inv.get("taxRate") != 0.06),
        ledger[0],
    )
    payload = {
        "type": "TAX_RATE_WRONG",
        "invoiceId": rate_issue.get("id"),
        "basis": "依据《发票合规指引》二、税率适用：增值税普通发票（服务类）应适用 6% 税率",
        "invoice": {
            "invoiceKind": rate_issue.get("invoiceKind"),
            "sellerName": (rate_issue.get("seller") or {}).get("name", ""),
            "taxRate": rate_issue.get("taxRate"),
            "totalFen": rate_issue.get("totalFen"),
        },
    }
    m3 = reviewer.review_m3_anomaly(payload, {"税率", "适用", "增值税", "发票"})
    print("M3 复核:", m3.get("verdict"), "| 校验通过:", "error" not in m3)

    print("LLM 统计:", reviewer.get_stats())
    print("SMOKE OK")


if __name__ == "__main__":
    main()
