"""
M3发票异常检测处理器（全量发票台账稽核）

检测项（以系统记录为准，台账口径）：
1. 重复报销：同一 invoiceCode+invoiceNo 出现在 2 次以上（确证）；
   疑似重复：同一号码出现在不同代码下（宁可错杀，交 AI/人工复核）
2. TITLE_WRONG：EXPENSE 发票购方抬头与公司全称不符
3. TAXNO_WRONG：EXPENSE 发票购方税号与公司税号不符（参考串 X 位不校验）
4. TAX_RATE_WRONG：发票税率与票种应适用税率不符
5. CONSECUTIVE_NO：同一代码下 ≥3 张连续号码（疑似拆分开票，交 AI/人工复核）
6. SUPPLIER_DUP：供应商重复档案（同税号下多个不同名称，访谈 zk-011）
另输出 supplierProfiles：疑似虚开供应商画像（开票集中 + 金额卡阈值 + 连号，zk-021 口径）

输出格式：
{
  "duplicateInvoices": [{"invoiceCode": "...", "invoiceNo": "...", "claimIds": [...]}],
  "invoiceIssues": [{"invoiceId": "...", "issue": "TITLE_WRONG|TAXNO_WRONG|TAX_RATE_WRONG"}]
}
"""

import os
import json
import re
from collections import defaultdict
from typing import Optional, List, Dict, Any

from core.client import QihengClient
from core.auditor import Auditor
from core.claim_store import build_invoice_index, fetch_all_claims
from data.config import COMPANY_NAME, COMPANY_TAX_NO
from core.logger import get_logger

logger = get_logger("m3")


# 票种 -> 应适用税率（与制度/发票合规指引一致）
EXPECTED_TAX_RATE = {
    "HOTEL": 0.06,
    "TRAIN": 0.09,
    "TAXI": 0.03,
    "FLIGHT": 0.09,
    "VAT_GENERAL": 0.06,
    "VAT_SPECIAL": 0.13,
}

# 疑似虚开画像阈值（可在环境变量覆盖，单位：分）
# 访谈线索（zk-010/zk-021）：连号开票 + 开票集中是最直接的怀疑信号，故默认 1 段连号即入画像
SUPPLIER_PROFILE_MIN_INVOICES = int(os.environ.get("M3_SUPPLIER_MIN_INVOICES", "3"))
SUPPLIER_PROFILE_LOW_AMOUNT_FEN = int(os.environ.get("M3_SUPPLIER_LOW_AMOUNT_FEN", "500000"))
SUPPLIER_PROFILE_LOW_RATIO = float(os.environ.get("M3_SUPPLIER_LOW_RATIO", "0.8"))
SUPPLIER_PROFILE_CONSEC_RUNS = int(os.environ.get("M3_SUPPLIER_CONSEC_RUNS", "1"))


def _norm_supplier_name(name: str) -> str:
    """供应商名称归一化：去空白/括号/公司后缀，用于重复档案比对"""
    s = re.sub(r"[\s\u3000()（）\[\]【】]", "", str(name or ""))
    for suffix in ("有限责任公司", "股份有限公司", "有限公司"):
        s = s.replace(suffix, "")
    return s


class M3Processor:
    """M3发票异常检测处理器"""

    def __init__(self, client: QihengClient) -> None:
        self.client: QihengClient = client
        self.duplicate_invoices: List[Dict[str, Any]] = []
        self.invoice_issues: List[Dict[str, str]] = []
        self.supplier_profiles: List[Dict[str, Any]] = []

    def run(self, limit: Optional[int] = None) -> Dict[str, Any]:
        """执行M3发票异常检测（全量发票台账扫描）"""
        logger.info("=== M3发票异常检测开始 ===")

        logger.info("\n[步骤1] 遍历全量发票台账...")
        invoices = list(self.client.invoices_iterate())
        if limit and limit > 0:
            invoices = invoices[:limit]
        logger.info(f"✓ 台账共 {len(invoices)} 张发票")

        # 缓存全量台账（供前端异常详情下钻使用）
        try:
            cache_dir = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), "output", "cache"
            )
            os.makedirs(cache_dir, exist_ok=True)
            with open(os.path.join(cache_dir, "invoice_ledger.json"), "w", encoding="utf-8") as f:
                json.dump(invoices, f, ensure_ascii=False)
        except OSError:
            pass

        logger.info("\n[步骤2] 加载报销单-发票关联（用于重复报销定位单据）...")
        claims = fetch_all_claims(self.client)
        claim_index = build_invoice_index(claims)
        logger.info(f"✓ 已加载 {len(claims)} 单报销单关联")

        logger.info("\n[步骤3] 检测重复发票...")
        self.detect_duplicate_invoices(invoices, claim_index)
        logger.info(f"✓ 发现 {len(self.duplicate_invoices)} 组重复发票")

        logger.info("\n[步骤4] 检测票面问题（抬头/税号/税率）...")
        self.detect_invoice_issues(invoices)
        logger.info(f"✓ 发现 {len(self.invoice_issues)} 个票面问题")

        logger.info("\n[步骤4.5] 检测供应商重复档案与疑似虚开画像...")
        self.detect_supplier_duplicates(invoices)
        self.build_supplier_profiles(invoices)
        logger.info(
            "✓ 供应商重复档案 %d 组，疑似虚开画像 %d 家",
            len([i for i in self.invoice_issues if i["issue"] == "SUPPLIER_DUP"]),
            len(self.supplier_profiles),
        )

        result = self.build_result()
        logger.info("\n=== M3发票异常检测完成 ===")
        return result

    def detect_duplicate_invoices(self, invoices: list, claim_index: dict) -> None:
        """重复发票：
        1) 精确重复：同一 code+no 出现在 2 次以上（确证）
        2) 疑似重复：同一号码出现在不同代码下（宁可错杀，交 AI/人工复核）
        """
        by_key: Dict[str, List[dict]] = {}
        for inv in invoices:
            code = (inv.get("invoiceCode") or "").strip()
            no = (inv.get("invoiceNo") or "").strip()
            if not code or not no:
                continue
            key = f"{code}/{no}"
            by_key.setdefault(key, []).append(inv)

        for key, group in by_key.items():
            if len(group) < 2:
                continue
            claim_ids = claim_index.get(key, [])
            if len(claim_ids) < 2:
                # 台账出现两次但索引只有一单：以台账为准，claimIds 留实际值
                pass
            code, no = key.split("/", 1)
            self.duplicate_invoices.append({
                "invoiceCode": code,
                "invoiceNo": no,
                "claimIds": sorted(set(claim_ids)),
                "suspected": False,
                "basis": "依据《费用报销管理办法 V3.2》第十七条：同一张发票不得重复报销"
                         "（发票代码+号码在台账中出现 2 次以上）",
            })

        # 疑似重复：同一发票号码出现在多个发票代码下（不同销方可能同号，需人工确认）
        by_no: Dict[str, set] = {}
        for inv in invoices:
            code = (inv.get("invoiceCode") or "").strip()
            no = (inv.get("invoiceNo") or "").strip()
            if not code or not no:
                continue
            by_no.setdefault(no, set()).add(code)
        for no, codes in by_no.items():
            if len(codes) < 2:
                continue
            codes_sorted = sorted(codes)
            claim_ids = sorted({
                cid
                for c in codes_sorted
                for cid in claim_index.get(f"{c}/{no}", [])
            })
            self.duplicate_invoices.append({
                "invoiceCode": codes_sorted[0],
                "invoiceNo": no,
                "otherCodes": codes_sorted[1:],
                "claimIds": claim_ids,
                "suspected": True,
                "basis": f"疑似重复：发票号码「{no}」出现在多个发票代码下（"
                         f"{', '.join(codes_sorted)}），可能为同一发票重复入账，需人工/AI 复核确认",
            })

    def detect_invoice_issues(self, invoices: list) -> None:
        """票面问题：仅稽核 EXPENSE 类发票（购方应为公司）"""
        for inv in invoices:
            invoice_id = inv.get("id", "")
            if not invoice_id:
                continue

            # 抬头/税号只稽核 EXPENSE（购方应为公司）；税率全类型稽核
            if inv.get("type") == "EXPENSE":
                buyer = inv.get("buyer") or {}
                buyer_name = Auditor._normalize_text(buyer.get("name", ""))
                company_name = Auditor._normalize_text(COMPANY_NAME)
                if buyer_name and buyer_name != company_name:
                    self.invoice_issues.append({
                        "invoiceId": invoice_id,
                        "issue": "TITLE_WRONG",
                        "basis": f"依据《发票合规指引》一、抬头与税号：发票抬头必须为"
                                 f"「{COMPANY_NAME}」全称，实为「{buyer_name}」",
                    })

                buyer_tax_no = buyer.get("taxNo", "")
                if buyer_tax_no and not Auditor._taxno_matches(buyer_tax_no, COMPANY_TAX_NO):
                    self.invoice_issues.append({
                        "invoiceId": invoice_id,
                        "issue": "TAXNO_WRONG",
                        "basis": f"依据《发票合规指引》一、抬头与税号：纳税人识别号必须为"
                                 f"「{COMPANY_TAX_NO}」，实为「{buyer_tax_no}」",
                    })

            self._check_tax_rate(inv)

        self._check_consecutive_no(invoices)

    def _check_consecutive_no(self, invoices: list) -> None:
        """疑似连号发票：同一发票代码下 ≥3 张连续号码（疑似拆分开票，宁可错杀）"""
        from collections import defaultdict
        by_code: Dict[str, List[tuple]] = defaultdict(list)
        for inv in invoices:
            code = (inv.get("invoiceCode") or "").strip()
            no = (inv.get("invoiceNo") or "").strip()
            if code and no and no.isdigit():
                by_code[code].append((int(no), inv))

        for code, lst in by_code.items():
            seen: Dict[int, List[dict]] = defaultdict(list)
            for num, inv in lst:
                seen[num].append(inv)
            nums = sorted(seen)
            start = 0
            while start < len(nums):
                end = start
                while end + 1 < len(nums) and nums[end + 1] == nums[end] + 1:
                    end += 1
                if end - start >= 2:
                    for num in nums[start:end + 1]:
                        for inv in seen[num]:
                            self.invoice_issues.append({
                                "invoiceId": inv.get("id", ""),
                                "issue": "CONSECUTIVE_NO",
                                "suspected": True,
                                "basis": f"疑似连号发票：代码 {code} 下号码 "
                                         f"{nums[start]}–{nums[end]} 连续出现，"
                                         "疑似拆分开票，需人工/AI 复核确认",
                            })
                start = end + 1

    def detect_supplier_duplicates(self, invoices: list) -> None:
        """供应商重复档案：同销方税号下，归一化名称存在 ≥2 个不同值（访谈 zk-011）"""
        by_tax: Dict[str, Dict[str, List[dict]]] = defaultdict(lambda: defaultdict(list))
        for inv in invoices:
            if inv.get("type") not in ("EXPENSE", "PURCHASE_INPUT"):
                continue
            seller = inv.get("seller") or {}
            tax = (seller.get("taxNo") or "").strip()
            name = (seller.get("name") or "").strip()
            if not tax or not name:
                continue
            by_tax[tax][_norm_supplier_name(name)].append(inv)

        for tax, groups in by_tax.items():
            if len(groups) < 2:
                continue
            names = sorted(groups)
            all_invs = [inv for invs in groups.values() for inv in invs]
            self.invoice_issues.append({
                "invoiceId": all_invs[0].get("id", ""),
                "issue": "SUPPLIER_DUP",
                "invoiceIds": [inv.get("id", "") for inv in all_invs],
                "basis": f"供应商重复档案：税号「{tax}」下存在 {len(names)} 个不同名称"
                         f"（{', '.join(names)}），共涉及 {len(all_invs)} 张发票，"
                         "疑似同一供应商重复建档（供应商档案管理要求）",
            })

    def build_supplier_profiles(self, invoices: list) -> None:
        """疑似虚开供应商画像：开票集中 + 金额卡阈值 + 连号（访谈 zk-021 口径）"""
        by_seller: Dict[tuple, List[dict]] = defaultdict(list)
        for inv in invoices:
            seller = inv.get("seller") or {}
            name = (seller.get("name") or "").strip()
            tax = (seller.get("taxNo") or "").strip()
            if not name:
                continue
            by_seller[(name, tax)].append(inv)

        for (name, tax), invs in by_seller.items():
            if len(invs) < SUPPLIER_PROFILE_MIN_INVOICES:
                continue
            total_fen = sum(inv.get("totalFen") or 0 for inv in invs)
            low_ratio = (
                sum(1 for inv in invs if (inv.get("totalFen") or 0) <= SUPPLIER_PROFILE_LOW_AMOUNT_FEN)
                / len(invs)
            )
            consec_runs = self._count_consecutive_runs(invs)
            month_share = self._max_month_share(invs)

            signals = []
            if consec_runs >= SUPPLIER_PROFILE_CONSEC_RUNS:
                signals.append(f"存在 {consec_runs} 段 ≥3 连号")
            if low_ratio >= SUPPLIER_PROFILE_LOW_RATIO:
                signals.append(f"{low_ratio:.0%} 发票金额 ≤ {SUPPLIER_PROFILE_LOW_AMOUNT_FEN / 100:.0f} 元")
            if month_share >= 0.8:
                signals.append(f"开票高度集中在单月（占 {month_share:.0%}）")
            if not signals:
                continue

            self.supplier_profiles.append({
                "sellerName": name,
                "sellerTaxNo": tax,
                "invoiceCount": len(invs),
                "totalFen": total_fen,
                "lowRatio": round(low_ratio, 3),
                "consecutiveRuns": consec_runs,
                "monthShare": round(month_share, 3),
                "invoiceIds": [inv.get("id", "") for inv in invs],
                "basis": f"疑似虚开画像：「{name}」开票 {len(invs)} 张且{'、'.join(signals)}，"
                         "需人工核实供应商资质与业务真实性",
            })

    @staticmethod
    def _count_consecutive_runs(invs: list) -> int:
        """统计发票代码内 ≥3 张连续号码的段数"""
        by_code = defaultdict(set)
        for inv in invs:
            code = (inv.get("invoiceCode") or "").strip()
            no = (inv.get("invoiceNo") or "").strip()
            if code and no and no.isdigit():
                by_code[code].add(int(no))
        runs = 0
        for nums in by_code.values():
            nums = sorted(nums)
            start = 0
            while start < len(nums):
                end = start
                while end + 1 < len(nums) and nums[end + 1] == nums[end] + 1:
                    end += 1
                if end - start >= 2:
                    runs += 1
                start = end + 1
        return runs

    @staticmethod
    def _max_month_share(invs: list) -> float:
        """单月开票占比（按开票日期前 7 位 YYYY-MM 聚合）"""
        months = defaultdict(int)
        for inv in invs:
            d = (inv.get("issuedOn") or "").strip()
            if len(d) >= 7:
                months[d[:7]] += 1
        if not months:
            return 0.0
        return max(months.values()) / sum(months.values())

    def _check_tax_rate(self, invoice: dict) -> None:
        """税率异常：与票种应适用税率不符"""
        kind = invoice.get("invoiceKind", "")
        expected = EXPECTED_TAX_RATE.get(kind)
        if expected is None:
            return
        actual = invoice.get("taxRate")
        if actual is None:
            return
        try:
            actual_float = float(actual)
        except (TypeError, ValueError):
            return
        if abs(actual_float - expected) > 1e-9:
            kind_label = {
                "HOTEL": "住宿服务", "TRAIN": "旅客运输（铁路）", "TAXI": "出租车客运",
                "FLIGHT": "旅客运输（航空）", "VAT_GENERAL": "增值税普通发票（服务类）",
                "VAT_SPECIAL": "增值税专用发票（货物/加工类）",
            }.get(kind, kind)
            self.invoice_issues.append({
                "invoiceId": invoice.get("id", ""),
                "issue": "TAX_RATE_WRONG",
                "basis": f"依据《发票合规指引》二、税率适用：{kind_label}应适用 "
                         f"{expected * 100:.0f}% 税率，实为 {actual_float * 100:.0f}%",
            })

    def build_result(self) -> dict:
        """构建M3结果"""
        return {
            "duplicateInvoices": self.duplicate_invoices,
            "invoiceIssues": self.invoice_issues,
            "supplierProfiles": self.supplier_profiles,
        }

    def get_results(self) -> dict:
        """获取检测结果"""
        return self.build_result()


if __name__ == "__main__":
    import os

    api_key = os.environ["QIHENG_API_KEY"]
    client = QihengClient(api_key=api_key)

    processor = M3Processor(client)
    result = processor.run()

    print(f"\n重复发票组数: {len(result['duplicateInvoices'])}")
    for dup in result["duplicateInvoices"]:
        print(f"  {dup['invoiceCode']} {dup['invoiceNo']}: {dup['claimIds']}")

    print(f"\n票面问题数: {len(result['invoiceIssues'])}")
    issue_counts = {}
    for issue in result["invoiceIssues"]:
        issue_counts[issue["issue"]] = issue_counts.get(issue["issue"], 0) + 1
    for issue_type, count in issue_counts.items():
        print(f"  {issue_type}: {count}")
