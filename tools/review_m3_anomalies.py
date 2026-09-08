"""
全量 AI 复核 M3 异常（DeepSeek 结合制度知识库）。

用法：python tools/review_m3_anomalies.py [--scope all|issues|duplicates] [--use-cached]
"""

import os
import sys
import json
import time
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

from core.llm_reviewer import LLMReviewer


def load_scan() -> dict:
    root = os.path.dirname(os.path.dirname(__file__))
    with open(os.path.join(root, "output", "reports", "m3_result.json"), encoding="utf-8") as f:
        scan = json.load(f)
    # 加载全量单据缓存做发票明细富化（与后端一致）
    cache_file = os.path.join(root, "output", "cache", "all_claims.json")
    ledger_file = os.path.join(root, "output", "cache", "invoice_ledger.json")
    claims = []
    if os.path.exists(cache_file):
        with open(cache_file, encoding="utf-8") as f:
            claims = json.load(f)
    inv_by_id = {}
    inv_by_key = {}
    for cl in claims:
        for ln in cl.get("lines", []):
            inv = ln.get("invoice") or {}
            if not inv.get("id"):
                continue
            d = {
                "claimNo": cl.get("claimNo", ""),
                "invoiceKind": inv.get("invoiceKind", ""),
                "issuedOn": inv.get("issuedOn", ""),
                "buyerName": (inv.get("buyer") or {}).get("name", ""),
                "buyerTaxNo": (inv.get("buyer") or {}).get("taxNo", ""),
                "sellerName": (inv.get("seller") or {}).get("name", ""),
                "totalFen": inv.get("totalFen"),
                "taxRate": inv.get("taxRate"),
            }
            inv_by_id.setdefault(inv["id"], d)
            inv_by_key.setdefault(f"{inv.get('invoiceCode','')}/{inv.get('invoiceNo','')}", []).append(d)
    for dup in scan.get("duplicateInvoices", []):
        dup["invoices"] = inv_by_key.get(f"{dup.get('invoiceCode','')}/{dup.get('invoiceNo','')}", [])
    for iss in scan.get("invoiceIssues", []):
        if iss.get("invoiceId") in inv_by_id:
            iss["invoice"] = inv_by_id[iss.get("invoiceId")]
        # 台账兜底：非报销类发票（采购进项）
        elif os.path.exists(ledger_file):
            with open(ledger_file, encoding="utf-8") as f:
                ledger = json.load(f)
            for inv in ledger:
                if inv.get("id") == iss.get("invoiceId"):
                    iss["invoice"] = {
                        "invoiceCode": inv.get("invoiceCode", ""),
                        "invoiceNo": inv.get("invoiceNo", ""),
                        "invoiceKind": inv.get("invoiceKind", ""),
                        "issuedOn": inv.get("issuedOn", ""),
                        "buyerName": (inv.get("buyer") or {}).get("name", ""),
                        "buyerTaxNo": (inv.get("buyer") or {}).get("taxNo", ""),
                        "sellerName": (inv.get("seller") or {}).get("name", ""),
                        "totalFen": inv.get("totalFen"),
                        "taxRate": inv.get("taxRate"),
                    }
                    break
    return scan


def build_payload(item: dict, kind: str) -> dict:
    if kind == "duplicate":
        return {
            "type": "重复报销",
            "invoiceCode": item.get("invoiceCode"),
            "invoiceNo": item.get("invoiceNo"),
            "claimIds": item.get("claimIds", []),
            "basis": item.get("basis", ""),
            "invoices": item.get("invoices", []),
        }
    inv = item.get("invoice") or {}
    return {
        "type": item.get("issue"),
        "invoiceId": item.get("invoiceId"),
        "basis": item.get("basis", ""),
        "invoice": inv,
    }


def keywords(item: dict, kind: str) -> set:
    if kind == "duplicate":
        return {"重复", "查重", "发票", "报销"}
    issue = item.get("issue", "")
    if issue == "TITLE_WRONG":
        return {"抬头", "发票", "全称", "分公司"}
    if issue == "TAXNO_WRONG":
        return {"税号", "纳税人识别号"}
    if issue == "TAX_RATE_WRONG":
        return {"税率", "适用", "增值税", "发票"}
    return {"发票", "合规"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", default="all", choices=["all", "issues", "duplicates"])
    args = parser.parse_args()

    scan = load_scan()
    tasks = []
    if args.scope in ("all", "issues"):
        tasks += [("issue", it) for it in scan.get("invoiceIssues", [])]
    if args.scope in ("all", "duplicates"):
        tasks += [("duplicate", it) for it in scan.get("duplicateInvoices", [])]

    reviewer = LLMReviewer()
    print(f"开始 AI 复核 {len(tasks)} 条异常（模型: {reviewer.model}）")
    results = {}
    failed = 0

    def _one(kind_item):
        kind, item = kind_item
        key = item.get("invoiceId") if kind == "issue" else f"{item.get('invoiceCode')}/{item.get('invoiceNo')}"
        try:
            out = reviewer.review_m3_anomaly(build_payload(item, kind), keywords(item, kind))
            return key, kind, out
        except Exception as e:
            return key, kind, {"error": str(e)[:200]}

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(_one, t) for t in tasks]
        for i, fut in enumerate(as_completed(futures), 1):
            key, kind, out = fut.result()
            results[f"{kind}:{key}"] = out
            if out.get("error"):
                failed += 1
            print(f"  [{i}/{len(tasks)}] {key} -> {out.get('verdict', 'ERR')}", flush=True)

    root = os.path.dirname(os.path.dirname(__file__))
    out_path = os.path.join(root, "output", "reports", "m3_ai_review.json")
    payload = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "model": reviewer.model,
        "scope": args.scope,
        "total": len(tasks),
        "failed": failed,
        "results": results,
        "fromCache": False,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    from collections import Counter
    verdicts = Counter(o.get("verdict") for o in results.values() if not o.get("error"))
    print("=" * 50)
    print(f"完成：{len(tasks)} 条，失败 {failed}，耗时 {round(time.time()-t0,1)}s")
    print("AI 结论分布:", dict(verdicts))
    print("报告已保存:", out_path)


if __name__ == "__main__":
    main()
