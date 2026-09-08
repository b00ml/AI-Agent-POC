"""
审核结果交叉验证脚本

对 output/reports/audit_report.json 与全量单据缓存做一致性校验：
1. 特批（SPECIAL_APPROVE）单据是否全部 APPROVE
2. 加班打车行是否都有 MISSING_APPROVAL_OVERTIME_TAXI 判定
3. 全量发票索引中的重复单据是否都被标记 DUPLICATE_INVOICE
4. migrated=false 附件是否触发 FLAG
5. 未知出差城市是否触发 FLAG

用法：python tools/verify_results.py
"""

import os
import sys
import json
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

from core.client import QihengClient
from core.claim_store import fetch_all_claims, build_invoice_index


def main() -> None:
    repo_root = os.path.dirname(os.path.dirname(__file__))
    report_path = os.path.join(repo_root, "output", "reports", "audit_report.json")
    with open(report_path, "r", encoding="utf-8") as f:
        report = json.load(f)

    reviews = report.get("reviews", [])
    verdict = {r["claimId"]: r for r in reviews}
    print(f"审核单据数: {len(reviews)}")
    print(f"结论分布: {Counter(r['result'] for r in reviews)}")

    client = QihengClient()
    claims = fetch_all_claims(client)
    pending = [c for c in claims if c.get("status") == "PENDING"]

    issues = []

    # 1. 特批单据
    for cl in pending:
        ap = client.approvals_for_claim(cl["id"])
        if any(a.get("action") == "SPECIAL_APPROVE" for a in ap):
            v = verdict.get(cl["id"])
            if not v or v["result"] != "APPROVE":
                issues.append(f"特批单据 {cl['id']} 结论 {v['result'] if v else '缺失'}，应为 APPROVE")
    print("1) 特批单据校验完成")

    # 2. 加班打车（无事前审批的必须标记；有审批的不得标记）
    ot_claims = set()
    for cl in pending:
        for ln in cl.get("lines", []):
            desc = ln.get("description", "")
            et = ln.get("expenseType", "")
            if et in ("TAXI", "CITY_TRANSPORT") and ("加班" in desc or "打车" in desc):
                ot_claims.add(cl["id"])
    ot_approval_claims = set()
    for cl in pending:
        if cl["id"] not in ot_claims:
            continue
        ap = client.approvals_for_claim(cl["id"])
        has_approval = any(
            a.get("action") == "SPECIAL_APPROVE"
            or (
                a.get("action") == "APPROVE"
                and any(k in (a.get("comment") or "") for k in ("加班", "打车", "出租车", "用车"))
            )
            for a in ap
        )
        if has_approval:
            ot_approval_claims.add(cl["id"])
    ot_missing_claims = ot_claims - ot_approval_claims
    flagged_ot = set(
        r["claimId"] for r in reviews
        if "MISSING_APPROVAL_OVERTIME_TAXI" in r["violations"]
    )
    for cid in sorted(ot_missing_claims - flagged_ot):
        issues.append(f"加班打车单据 {cid} 未标记 MISSING_APPROVAL_OVERTIME_TAXI")
    for cid in sorted(flagged_ot - ot_missing_claims):
        issues.append(f"单据 {cid} 标记缺加班审批，但持有事前审批或无加班打车行")
    print(
        f"2) 加班打车校验完成: 行数 {len(ot_claims)}，"
        f"缺审批 {len(ot_missing_claims)}，持审批 {len(ot_approval_claims)}，标记 {len(flagged_ot)}"
    )

    # 3. 重复发票
    index = build_invoice_index(claims)
    dup_pending = set()
    for key, cids in index.items():
        if len(cids) > 1 and any(cid in verdict for cid in cids):
            for cid in cids:
                if cid in verdict:
                    dup_pending.add(cid)
    flagged_dup = set(
        r["claimId"] for r in reviews
        if "DUPLICATE_INVOICE" in r["violations"]
    )
    for cid in sorted(dup_pending - flagged_dup):
        issues.append(f"重复报销单据 {cid} 未标记 DUPLICATE_INVOICE")
    for cid in sorted(flagged_dup - dup_pending):
        issues.append(f"单据 {cid} 标记重复但索引中无对应重复")
    print(f"3) 重复发票校验完成: 应标记 {len(dup_pending)}，实际标记 {len(flagged_dup)}")

    # 4. migrated=false 附件
    for cl in pending:
        for ln in cl.get("lines", []):
            att = ln.get("attachment") or {}
            if att.get("migrated") is False:
                v = verdict.get(cl["id"])
                if not v or v["result"] != "FLAG":
                    issues.append(f"单据 {cl['id']} 存在未迁移附件，结论应为 FLAG")
    print("4) 附件迁移校验完成")

    # 5. 未知城市
    from data.travel_data import TravelDataManager
    tm = TravelDataManager(client)
    tm.load_data()
    for cl in pending:
        trip = cl.get("trip") or {}
        city = trip.get("city")
        if city and not tm.has_city(city):
            v = verdict.get(cl["id"])
            if not v or v["result"] != "FLAG":
                issues.append(f"单据 {cl['id']} 城市 {city} 未知，结论应为 FLAG")
    print("5) 未知城市校验完成")

    print("\n=== 校验结果 ===")
    if issues:
        print(f"发现 {len(issues)} 个不一致:")
        for it in issues[:30]:
            print("  -", it)
    else:
        print("全部一致，无异常。")


if __name__ == "__main__":
    main()
