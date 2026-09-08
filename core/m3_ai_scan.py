"""
M3 AI 全量巡检（分批初筛）

把全量发票台账按批压缩成摘要发给 LLM 做合规初筛，找出规则引擎
覆盖不到的疑似异常（金额异常、票种不符、日期异常、连号发票等）。
规则引擎继续作为全量兜底；AI 结果仅作「疑似清单」，供人工复核。

设计约束：
- AI 只报疑似，不修改任何状态
- 分批调用控制成本：批数 = ceil(发票数 / batch_size)，而非逐张调用
- 输出结果中的 invoiceId 必须来自本批数据（校验防幻觉）
"""

import os
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, List, Dict, Any

from core.llm_reviewer import LLMReviewer
from data.config import COMPANY_NAME, COMPANY_TAX_NO
from core.logger import get_logger

logger = get_logger("m3_ai_scan")


def _load_prompt() -> str:
    prompt_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "data", "prompts", "m3_full_scan.txt",
    )
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read()


FULL_SCAN_PROMPT_TEMPLATE = _load_prompt()


def _invoice_summary(inv: dict) -> dict:
    """把发票压成紧凑摘要，控制单批 token 量"""
    buyer = inv.get("buyer") or {}
    seller = inv.get("seller") or {}
    total_fen = inv.get("totalFen")
    return {
        "id": inv.get("id", ""),
        "kind": inv.get("invoiceKind", ""),
        "type": inv.get("type", ""),
        "no": f"{inv.get('invoiceCode', '')}/{inv.get('invoiceNo', '')}",
        "issuedOn": inv.get("issuedOn", ""),
        "rate": inv.get("taxRate"),
        "totalYuan": round((total_fen or 0) / 100, 2) if total_fen is not None else None,
        "buyer": buyer.get("name", ""),
        "seller": seller.get("name", ""),
    }


def run_full_scan(
    invoices: List[dict],
    batch_size: int = 60,
    limit: Optional[int] = None,
    max_workers: int = 4,
    progress_cb=None,
) -> Dict[str, Any]:
    """对发票列表分批执行 AI 全量巡检，返回疑似异常清单。

    Args:
        invoices: 全量发票台账
        batch_size: 每批发票数（默认 60）
        limit: 只巡检前 N 张（演示/测试用小批量）
        max_workers: 并行批次数
        progress_cb: (total_batches, done_batches) 进度回调
    """
    if limit and limit > 0:
        invoices = invoices[:limit]

    if not invoices:
        return {
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            "model": "",
            "totalInvoices": 0,
            "batchSize": batch_size,
            "batchCount": 0,
            "failedBatches": 0,
            "flaggedCount": 0,
            "results": {},
        }

    batches = [
        invoices[i:i + batch_size]
        for i in range(0, len(invoices), batch_size)
    ]
    reviewer = LLMReviewer()
    results: Dict[str, dict] = {}
    failed_batches = 0

    def _one(batch: List[dict]) -> List[tuple]:
        summary = [_invoice_summary(inv) for inv in batch]
        prompt = FULL_SCAN_PROMPT_TEMPLATE.format(
            company_name=COMPANY_NAME,
            company_tax_no=COMPANY_TAX_NO,
            batch_json=json.dumps(summary, ensure_ascii=False),
        )
        parsed = reviewer.client.chat_json(prompt, trace_id="m3-scan")
        if not parsed:
            return []
        valid_ids = {inv.get("id") for inv in batch if inv.get("id")}
        out = []
        for it in parsed.get("suspicions") or []:
            iid = it.get("invoiceId")
            if iid in valid_ids:
                out.append((iid, it))
        return out

    done = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_one, b) for b in batches]
        for fut in as_completed(futures):
            try:
                for iid, it in fut.result():
                    results[iid] = it
            except Exception as e:
                failed_batches += 1
                logger.warning(f"  ✗ AI 巡检批次失败: {type(e).__name__}: {e}")
            done += 1
            if progress_cb:
                progress_cb(len(batches), done)

    return {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "model": reviewer.model,
        "totalInvoices": len(invoices),
        "batchSize": batch_size,
        "batchCount": len(batches),
        "failedBatches": failed_batches,
        "flaggedCount": len(results),
        "results": results,
    }
