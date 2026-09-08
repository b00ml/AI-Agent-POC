"""
AI 复核助手评测：30 单公开样例上对比「规则引擎」与「LLM 独立复核」。

指标：
- 双方各自的驳回判定 F1（REJECT/FLAG 均视为「提请关注」）
- 违规代码完全一致率
- 整体准确率
- LLM 与规则引擎的意见一致率（分歧即应提请人工复核）

用法：python tools/eval_llm_reviewer.py [--skip-llm]
"""

import os
import sys
import json
import time
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

from core.client import QihengClient
from core.auditor import Auditor
from core.claim_store import load_invoice_index
from core.llm_reviewer import LLMReviewer
from data.travel_data import TravelDataManager


def load_ocr_cache() -> dict:
    root = os.path.dirname(os.path.dirname(__file__))
    cache = {}
    for name in ("ocr_all_paddle.json", "ocr_samples_paddle.json"):
        path = os.path.join(root, "output", "cache", name)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                cache.update(json.load(f))
    return cache


def metrics(rows: list, result_key: str, violations_key: str) -> dict:
    """按二分类（提请关注=REJECT/FLAG）计算 F1 等指标"""
    tp = tn = fp = fn = 0
    vmatch = 0
    vtotal = 0
    for r in rows:
        actual = r["expectedVerdict"] == "REJECT"
        pred = r[result_key] == "REJECT" or r[result_key] == "FLAG"
        if pred and actual:
            tp += 1
        elif pred and not actual:
            fp += 1
        elif not pred and actual:
            fn += 1
        else:
            tn += 1
        if actual:
            vtotal += 1
            if set(r["expectedViolations"]) == set(r[violations_key] or []):
                vmatch += 1
    precision = tp / (tp + fp) if tp + fp else 0
    recall = tp / (tp + fn) if tp + fn else 0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0
    return {
        "f1": round(f1, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "accuracy": round((tp + tn) / len(rows), 4),
        "violationMatchRate": round(vmatch / vtotal, 4) if vtotal else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-llm", action="store_true", help="只算规则引擎基线，不调 LLM")
    parser.add_argument("--limit", type=int, default=0, help="只评测前 N 单（分批防超时）")
    parser.add_argument("--offset", type=int, default=0, help="从第 N 单开始（配合 --limit 分批）")
    args = parser.parse_args()

    root = os.path.dirname(os.path.dirname(__file__))
    labels = json.load(open(
        os.path.join(root, "data", "labels", "public-sample-labels.json"),
        encoding="utf-8",
    ))["claims"]

    client = QihengClient()
    tm = TravelDataManager(client)
    tm.load_data()
    auditor = Auditor(tm)
    auditor.set_invoice_index(load_invoice_index(client))
    ocr_cache = load_ocr_cache()
    reviewer = None if args.skip_llm else LLMReviewer()

    rows = []
    items = list(labels.items())
    if args.limit > 0:
        items = items[args.offset:args.offset + args.limit]
    for cid, exp in items:
        detail = client.expense_claims_get(cid)
        approvals = client.approvals_for_claim(cid)

        ocr_results = {}
        for ln in detail.get("lines", []):
            att = ln.get("attachment") or {}
            if att and att.get("id") in ocr_cache:
                ocr_results[att["id"]] = ocr_cache[att["id"]]

        audit = auditor.audit_claim(detail, approvals, ocr_results=ocr_results)
        rules_result = audit.result
        rules_violations = [v.code for v in audit.violations]
        rules_reasons = audit.reasons

        llm_result = None
        llm_violations = []
        llm_agree = None
        llm_latency = None
        if reviewer:
            try:
                opinion = {
                    "result": rules_result,
                    "violations": rules_violations,
                    "reasons": rules_reasons,
                }
                _t0 = time.time()
                out = reviewer.review_claim(
                    detail, approvals,
                    travel_standards=tm.list_standards(),
                    ocr_fields=ocr_results,
                    rules_opinion=opinion,
                )
                llm_latency = round(time.time() - _t0, 2)
                llm_result = out.get("result")
                llm_violations = out.get("violations") or []
                llm_agree = out.get("agreeWithRules")
                if not llm_agree:
                    print(f"  [分歧] {cid}: 规则={rules_result} vs LLM={llm_result} "
                          f"规则违规={rules_violations} LLM违规={llm_violations}")
            except Exception as e:
                print(f"  [LLM失败] {cid}: {e}")

        rows.append({
            "claimId": cid,
            "expectedVerdict": exp.get("expectedVerdict"),
            "expectedViolations": exp.get("violations", []),
            "rulesResult": rules_result,
            "rulesViolations": rules_violations,
            "llmResult": llm_result,
            "llmViolations": llm_violations,
            "llmAgree": llm_agree,
            "llmLatencySec": llm_latency,
        })
        time.sleep(0.3)  # 温和限流

    rules_m = metrics(rows, "rulesResult", "rulesViolations")
    llm_m = metrics(rows, "llmResult", "llmViolations") if not args.skip_llm else None
    agree_rate = None
    if reviewer:
        decided = [r for r in rows if r["llmResult"] in ("APPROVE", "REJECT", "FLAG")]
        agree_rate = round(
            sum(1 for r in decided if r["llmAgree"]) / len(decided), 4
        ) if decided else None

    print("\n=== 评测结果 ===")
    print(f"样例数: {len(rows)}")
    print(f"规则引擎: F1={rules_m['f1']} 准确率={rules_m['accuracy']} "
          f"违规一致率={rules_m['violationMatchRate']}")
    if llm_m:
        print(f"LLM复核 : F1={llm_m['f1']} 准确率={llm_m['accuracy']} "
              f"违规一致率={llm_m['violationMatchRate']}")
        print(f"LLM与规则意见一致率: {agree_rate}")
        latencies = [r["llmLatencySec"] for r in rows if r.get("llmLatencySec")]
        if latencies:
            print(f"LLM平均延迟: {sum(latencies) / len(latencies):.2f}s "
                  f"(n={len(latencies)})")
        if reviewer and getattr(reviewer, "client", None):
            print(f"LLM调用统计: {reviewer.get_stats()}")

    out_path = os.path.join(root, "output", "llm_review_eval.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "sampleSize": len(rows),
            "rules": rules_m,
            "llm": llm_m,
            "agreeRate": agree_rate,
            "details": rows,
        }, f, ensure_ascii=False, indent=2)
    print(f"报告已保存: {out_path}")


if __name__ == "__main__":
    main()
