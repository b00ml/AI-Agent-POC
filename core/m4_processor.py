"""
M4 银行对账处理器（加分项）

输入：
- bank/*.csv（网银导出，GBK 编码，第 6 行为表头）
- /v1/receivables 应收台账（需 receivable:read 权限）

匹配原则（对齐出纳吴珍「宁缺毋滥」要求）：
- 只处理贷方（收款）流水；借方（付款/工资/税费）视为无关
- 匹配顺序：户名精确 → bank/customer_aliases.json 别名 → 名称归一化 → 名称包含
- 金额匹配：完全一致；±10 元容差（跨行手续费差额）；一笔多票按应收合计拆分
- 仅输出高置信匹配（候选唯一）；名称不符、多候选、无头款等一律列入 unidentified
  并附原因，绝不强行匹配（错配比不匹配更糟）

输出：
{
  "matches": [{"txnId": "...", "receivableIds": ["AR-..."], "amountFen": 0, "note": ""}],
  "unidentified": [{"txnId": "...", "reason": "..."}],
  "statistics": {"matched": 0, "unidentified": 0, "total": 0, "matchedRate": 0.0}
}
"""

import os
import csv
import glob
import json
import re
import io
import time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from itertools import combinations
from typing import Optional, List, Dict, Any

from core.client import QihengClient
from core.logger import get_logger

logger = get_logger("m4")

# 银行流水目录：优先环境变量，默认仓库内 bank/（自包含交付）
BANK_DIR = os.environ.get("QIHENG_BANK_DIR") or os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "bank",
)

# 跨行手续费容差（分）：流水金额与应收余款差额不超过该值视为一致
AMOUNT_TOLERANCE_FEN = int(os.environ.get("QIHENG_M4_TOLERANCE_FEN", "1000"))
# 一笔多票拆分时参与组合的最大发票张数
MAX_SPLIT_ITEMS = 6
# 防止异常客户数据造成候选集合和组合搜索失控。超限只进入人工认领。
MAX_CANDIDATES = int(os.environ.get("QIHENG_M4_MAX_CANDIDATES", "50"))
MAX_COMBINATIONS = int(os.environ.get("QIHENG_M4_MAX_COMBINATIONS", "2000"))
COMBINATION_BUDGET_MS = int(os.environ.get("QIHENG_M4_COMBINATION_BUDGET_MS", "100"))

# 未识别流水的原因分类（设计文档2.0 §3.6⑦：例外清单按原因分类）
UNIDENTIFIED_CATEGORY_LABELS = {
    "NO_CUSTOMER": "户名无对应未清应收（无头款/个人账户/别名未登记）",
    "AMOUNT_OR_CANDIDATE": "金额不匹配或候选不唯一",
    "AMBIGUOUS_CANDIDATE": "候选或组合搜索超过安全预算",
    "DUPLICATE_TXN": "交易流水号重复",
    "NON_POSITIVE": "金额非正",
}


def _categorize_unidentified(reason: str) -> str:
    """把 unidentified 的原因文本归到枚举类别"""
    if "无对应未清应收" in reason:
        return "NO_CUSTOMER"
    if "金额非正" in reason:
        return "NON_POSITIVE"
    if "交易流水号重复" in reason:
        return "DUPLICATE_TXN"
    if "超过上限" in reason or "超过时间预算" in reason:
        return "AMBIGUOUS_CANDIDATE"
    return "AMOUNT_OR_CANDIDATE"


def _load_aliases(bank_dir: str) -> Dict[str, str]:
    """加载客户别名对照表（bank/customer_aliases.json），忽略 _ 开头的说明键"""
    path = os.path.join(bank_dir, "customer_aliases.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {
        str(k).strip(): str(v).strip()
        for k, v in data.items()
        if not str(k).startswith("_") and v
    }


def _norm_name(name: str) -> str:
    """名称归一化：去空白/括号/标点，去公司后缀，用于模糊匹配"""
    s = re.sub(r"[\s\u3000()（）\[\]【】•·\-—]", "", str(name or ""))
    for suffix in ("有限责任公司", "股份有限公司", "有限公司"):
        s = s.replace(suffix, "")
    return s


_HEADER_ALIASES = {
    "date": {"日期", "交易日期", "记账日期"},
    "direction": {"借贷标志", "借贷方向", "收付", "借贷"},
    "amount": {"交易金额", "金额", "发生额", "收入金额"},
    "payer": {"对方户名", "付款人", "对方名称", "户名"},
    "txn_id": {"交易流水号", "流水号", "交易编号", "凭证号"},
}


def _decode_csv(path: str) -> tuple[str, str]:
    """按常见银行导出编码解码，优先 UTF-8，再尝试 GB18030/GBK。"""
    raw = open(path, "rb").read()
    errors = []
    for encoding in ("utf-8-sig", "gb18030", "gbk"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError as exc:
            errors.append(f"{encoding}: {exc}")
    raise UnicodeDecodeError("bank-csv", raw, 0, len(raw), "; ".join(errors))


def _find_header(rows: List[List[str]]) -> tuple[Optional[int], Dict[str, int]]:
    """按列名定位表头，不依赖银行导出文件前置说明行数量。"""
    for row_index, row in enumerate(rows):
        mapping: Dict[str, int] = {}
        for field, aliases in _HEADER_ALIASES.items():
            for index, value in enumerate(row):
                if str(value).strip().strip('"') in aliases:
                    mapping[field] = index
                    break
        if {"direction", "amount", "payer", "txn_id"}.issubset(mapping):
            return row_index, mapping
    return None, {}


def _parse_amount_fen(value: str) -> Optional[int]:
    """把银行金额按分解析，避免 float 二进制误差。"""
    text = str(value or "").strip().strip('"').replace(",", "")
    if not text:
        return None
    try:
        amount = Decimal(text).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return None
    return int(amount * 100)


def parse_bank_csv_detailed(path: str) -> Dict[str, Any]:
    """解析网银流水并返回收款行、解析错误和重复流水号。"""
    credits = []
    parse_errors: List[Dict[str, Any]] = []
    try:
        text, encoding = _decode_csv(path)
        rows = list(csv.reader(io.StringIO(text)))
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        return {
            "credits": [],
            "parseErrors": [{"file": path, "row": None, "reason": f"文件解析失败: {exc}"}],
            "duplicateTxnIds": [],
            "encoding": None,
        }

    header_index, columns = _find_header(rows)
    if header_index is None:
        return {
            "credits": [],
            "parseErrors": [{"file": path, "row": None, "reason": "未找到包含收付方向、金额、对方户名和流水号的表头"}],
            "duplicateTxnIds": [],
            "encoding": encoding,
        }

    direction_values = {"贷", "收入", "收", "入账", "贷方"}
    for row_number, row in enumerate(rows[header_index + 1:], start=header_index + 2):
        max_index = max(columns.values())
        if len(row) <= max_index:
            if any(str(value).strip() for value in row):
                parse_errors.append({"file": path, "row": row_number, "reason": "列数不足"})
            continue
        direction = row[columns["direction"]].strip()
        if direction not in direction_values:
            continue
        txn_id = row[columns["txn_id"]].strip()
        if not txn_id:
            parse_errors.append({"file": path, "row": row_number, "reason": "贷方流水缺少交易流水号"})
            continue
        amount_fen = _parse_amount_fen(row[columns["amount"]])
        if amount_fen is None:
            parse_errors.append({"file": path, "row": row_number, "reason": "贷方金额无法解析"})
            continue
        date_index = columns.get("date")
        credits.append({
            "txnId": txn_id,
            "date": row[date_index].strip() if date_index is not None else "",
            "amountFen": amount_fen,
            "payer": row[columns["payer"]].strip(),
            "sourceFile": path,
            "sourceRow": row_number,
        })
    seen = set()
    duplicate_ids = set()
    for credit in credits:
        txn_id = credit["txnId"]
        if txn_id in seen:
            duplicate_ids.add(txn_id)
        seen.add(txn_id)
    return {
        "credits": credits,
        "parseErrors": parse_errors,
        "duplicateTxnIds": sorted(duplicate_ids),
        "encoding": encoding,
    }


def parse_bank_csv(path: str) -> List[Dict[str, Any]]:
    """兼容旧调用方：解析网银流水并返回贷方（收款）流水。"""
    return parse_bank_csv_detailed(path)["credits"]


class M4Processor:
    """M4 银行对账处理器"""

    def __init__(self, client: QihengClient) -> None:
        self.client = client

    def run(self, bank_dir: Optional[str] = None) -> Dict[str, Any]:
        """执行银行对账"""
        bank_dir = bank_dir or BANK_DIR
        logger.info("=== M4 银行对账开始 ===")

        credits: List[Dict[str, Any]] = []
        parse_errors: List[Dict[str, Any]] = []
        duplicate_txn_ids = set()
        for path in sorted(glob.glob(os.path.join(bank_dir, "*.csv"))):
            parsed = parse_bank_csv_detailed(path)
            rows = parsed["credits"]
            parse_errors.extend(parsed["parseErrors"])
            duplicate_txn_ids.update(parsed["duplicateTxnIds"])
            logger.info(
                f"  {os.path.basename(path)}: {len(rows)} 笔收款，"
                f"{len(parsed['parseErrors'])} 条解析异常"
            )
            credits.extend(rows)
        # 同一流水号跨文件重复时也必须进入人工认领，不能重复冲销应收。
        counts: Dict[str, int] = {}
        for credit in credits:
            counts[credit["txnId"]] = counts.get(credit["txnId"], 0) + 1
        duplicate_txn_ids.update(txn_id for txn_id, count in counts.items() if count > 1)
        logger.info(f"✓ 共 {len(credits)} 笔收款流水")

        receivables = list(self.client._paginate("/v1/receivables", {"limit": 200}))
        open_ar = [r for r in receivables if r.get("status") in ("OPEN", "OVERDUE")]
        logger.info(f"✓ 应收台账 {len(receivables)} 条，其中未清 {len(open_ar)} 条")

        aliases = _load_aliases(bank_dir)
        logger.info(f"✓ 别名对照表 {len(aliases)} 条")

        # 客户名索引：全称 / 别名值 / 归一化 / 归一化包含
        customer_index = {}  # norm_name -> [ar]
        for ar in open_ar:
            customer_index.setdefault(_norm_name(ar.get("customerName", "")), []).append(ar)

        def resolve_ars(payer: str) -> tuple[List[dict], bool]:
            """按顺序解析付款人对应的未清应收：精确 → 别名 → 归一化 → 包含"""
            exact = [ar for ar in open_ar if ar.get("customerName") == payer]
            if exact:
                candidates = exact
            elif payer in aliases:
                alias_target = aliases[payer]
                candidates = [ar for ar in open_ar if ar.get("customerName") == alias_target]
            else:
                norm_payer = _norm_name(payer)
                if norm_payer in customer_index:
                    candidates = customer_index[norm_payer]
                else:
                    contains = []
                    for key, ars in customer_index.items():
                        if key and (key in norm_payer or norm_payer in key):
                            contains.extend(ars)
                    candidates = list({ar.get("id"): ar for ar in contains}.values())
            return candidates, len(candidates) > MAX_CANDIDATES

        def find_split_ids(ars: List[dict], amount: int) -> tuple[List[str], Optional[str]]:
            """在组合数和墙钟时间预算内搜索一笔多票，超限返回明确原因。"""
            small = [ar for ar in ars if 0 < ar.get("outstandingFen", 0) <= amount]
            checked = 0
            started = time.perf_counter()
            for n in range(1, min(MAX_SPLIT_ITEMS, len(small)) + 1):
                combos_found = []
                for combo in combinations(small, n):
                    checked += 1
                    if checked > MAX_COMBINATIONS:
                        return [], f"组合搜索超过上限（{MAX_COMBINATIONS}）"
                    if (time.perf_counter() - started) * 1000 > COMBINATION_BUDGET_MS:
                        return [], f"组合搜索超过时间预算（{COMBINATION_BUDGET_MS}ms）"
                    if sum(a["outstandingFen"] for a in combo) == amount:
                        combos_found.append(combo)
                        if len(combos_found) > 1:
                            return [], "金额匹配组合不唯一"
                if len(combos_found) == 1:
                    return [a["id"] for a in combos_found[0]], None
            return [], None

        matches = []
        unidentified = []
        tol_fen = AMOUNT_TOLERANCE_FEN

        for cr in credits:
            amount = cr["amountFen"]
            if cr["txnId"] in duplicate_txn_ids:
                unidentified.append({
                    "txnId": cr["txnId"],
                    "reason": "交易流水号重复，需人工核验后再认领",
                })
                continue
            if amount <= 0:
                unidentified.append({"txnId": cr["txnId"], "reason": "金额非正"})
                continue
            ars, candidate_overflow = resolve_ars(cr["payer"])
            if not ars:
                unidentified.append({
                    "txnId": cr["txnId"],
                    "reason": f"户名「{cr['payer']}」无对应未清应收（可能为无头款/个人账户/别名未登记）",
                })
                continue
            if candidate_overflow:
                unidentified.append({
                    "txnId": cr["txnId"],
                    "reason": f"付款人候选应收超过上限（{MAX_CANDIDATES}），需人工认领",
                })
                continue

            # 1) 金额完全一致
            exact_ids = [ar["id"] for ar in ars if ar.get("outstandingFen") == amount]
            # 2) 金额在容差内（跨行手续费差额）
            tol_ids = [
                ar["id"] for ar in ars
                if ar.get("outstandingFen") is not None
                and abs(ar["outstandingFen"] - amount) <= tol_fen
            ]
            # 3) 部分付款：只有 ERP 明确返回累计付款字段时，唯一应收才可自动认领。
            # 仅凭 outstandingFen 无法证明这笔流水属于该应收，缺少字段时转人工。
            unique_partial = []
            payment_history_keys = ("paidFen", "receivedFen", "paidAmountFen", "cumulativePaidFen")
            has_payment_history = any(key in ars[0] for key in payment_history_keys) if len(ars) == 1 else False
            if len(ars) == 1 and has_payment_history and 0 < ars[0].get("outstandingFen", 0):
                unique_partial = [ars[0]["id"]]
            if len(exact_ids) == 1:
                matches.append({
                    "txnId": cr["txnId"],
                    "receivableIds": [exact_ids[0]],
                    "amountFen": amount,
                    "note": "金额一致",
                })
            elif len(tol_ids) == 1:
                matched_ar = next(a for a in ars if a["id"] == tol_ids[0])
                diff = abs(matched_ar["outstandingFen"] - amount) / 100
                matches.append({
                    "txnId": cr["txnId"],
                    "receivableIds": [tol_ids[0]],
                    "amountFen": amount,
                    "note": f"金额差 {diff:.2f} 元（容差内）",
                })
            elif unique_partial:
                matches.append({
                    "txnId": cr["txnId"],
                    "receivableIds": unique_partial,
                    "amountFen": amount,
                    "note": "部分付款（客户名下唯一未清应收）",
                })
            else:
                # 4) 只有单票/部分付款均不成立时，才执行有明确预算的多票组合搜索。
                split_ids, split_error = find_split_ids(ars, amount)
                if split_ids:
                    matches.append({
                        "txnId": cr["txnId"],
                        "receivableIds": split_ids,
                        "amountFen": amount,
                        "note": f"一笔多票拆分（{len(split_ids)} 张应收合计）",
                    })
                else:
                    unidentified.append({
                        "txnId": cr["txnId"],
                        "reason": (
                            f"{split_error}，需人工认领"
                            if split_error
                            else "金额不匹配或候选不唯一，需人工认领"
                        ),
                    })

        total = len(matches) + len(unidentified)
        matched_rate = round(len(matches) / total, 4) if total else 0.0

        # 例外按原因分类聚合：回答「剩下没匹配上的是什么」
        by_reason: Dict[str, int] = {}
        for u in unidentified:
            cat = _categorize_unidentified(u["reason"])
            by_reason[cat] = by_reason.get(cat, 0) + 1
        unidentified_by_reason = [
            {"category": cat, "label": UNIDENTIFIED_CATEGORY_LABELS[cat], "count": n}
            for cat, n in sorted(by_reason.items(), key=lambda kv: -kv[1])
        ]
        logger.info(f"✓ 匹配 {len(matches)} 笔，未识别 {len(unidentified)} 笔，匹配率 {matched_rate:.1%}")
        for item in unidentified_by_reason:
            logger.info(f"  例外 {item['label']}: {item['count']} 笔")
        return {
            "matches": matches,
            "unidentified": unidentified,
            "statistics": {
                "matched": len(matches),
                "unidentified": len(unidentified),
                "total": total,
                "matchedRate": matched_rate,
                "unidentifiedByReason": unidentified_by_reason,
                "parseErrors": parse_errors,
                "duplicateTxnIds": sorted(duplicate_txn_ids),
            },
        }


if __name__ == "__main__":
    import os as _os
    from dotenv import load_dotenv
    load_dotenv()

    client = QihengClient(api_key=_os.environ.get("QIHENG_M4_API_KEY"))
    processor = M4Processor(client)
    result = processor.run()
    print(json.dumps(result, ensure_ascii=False, indent=1)[:2000])
