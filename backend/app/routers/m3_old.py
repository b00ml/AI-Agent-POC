"""
M3 异常检测路由
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.jobs import start_job, update_progress, get_job

router = APIRouter()


class ScanRequest(BaseModel):
    apiUrl: str = ""
    apiKey: str = ""
    scope: str = "all"  # all = 全量发票台账（以系统记录为准）
    limit: Optional[int] = None
    useCached: bool = False


class AIReviewRequest(BaseModel):
    apiUrl: str = ""
    apiKey: str = ""
    scope: str = "all"  # all / issues / duplicates
    useCached: bool = False


class AIScanRequest(BaseModel):
    apiUrl: str = ""
    apiKey: str = ""
    scope: str = "all"
    limit: Optional[int] = None      # 只巡检前 N 张（演示/测试用小批量；None=全量）
    batchSize: int = 60              # 每批发票数
    useCached: bool = False          # 是否使用已缓存台账（默认拉取最新）


def _anomaly_keywords(item: dict, kind: str) -> set:
    if kind == "duplicate":
        return {"重复", "查重", "发票", "报销"}
    issue = item.get("issue", "")
    if issue == "TITLE_WRONG":
        return {"抬头", "发票", "全称", "分公司"}
    if issue == "TAXNO_WRONG":
        return {"税号", "纳税人识别号", "抬头"}
    if issue == "TAX_RATE_WRONG":
        return {"税率", "适用", "增值税", "发票"}
    if issue == "CONSECUTIVE_NO":
        return {"连号", "发票", "连续", "拆分", "开具"}
    if issue == "SUPPLIER_DUP":
        return {"供应商", "重复", "档案", "税号", "建档"}
    return {"发票", "合规"}


def _build_anomaly_payload(item: dict, kind: str) -> dict:
    if kind == "duplicate":
        return {
            "type": "重复报销",
            "invoiceCode": item.get("invoiceCode"),
            "invoiceNo": item.get("invoiceNo"),
            "claimIds": item.get("claimIds", []),
            "basis": item.get("basis", ""),
            "invoices": [
                {
                    "claimNo": i.get("claimNo"),
                    "invoiceKind": i.get("invoiceKind"),
                    "issuedOn": i.get("issuedOn"),
                    "buyerName": i.get("buyerName"),
                    "sellerName": i.get("sellerName"),
                    "totalFen": i.get("totalFen"),
                }
                for i in item.get("invoices", [])
            ],
        }
    inv = item.get("invoice") or {}
    return {
        "type": item.get("issue"),
        "invoiceId": item.get("invoiceId"),
        "basis": item.get("basis", ""),
        "invoice": {
            "invoiceCode": inv.get("invoiceCode"),
            "invoiceNo": inv.get("invoiceNo"),
            "invoiceKind": inv.get("invoiceKind"),
            "issuedOn": inv.get("issuedOn"),
            "buyerName": inv.get("buyerName"),
            "buyerTaxNo": inv.get("buyerTaxNo"),
            "sellerName": inv.get("sellerName"),
            "taxRate": inv.get("taxRate"),
            "totalFen": inv.get("totalFen"),
        },
    }


def _build_invoice_detail_map(claims: list):
    """从全量单据 + 台账缓存解析发票明细映射（供异常/巡检结果下钻）"""
    import os
    import json
    from pathlib import Path
    inv_by_id = {}
    inv_by_key = {}
    for cl in claims:
        for ln in cl.get("lines", []):
            inv = ln.get("invoice") or {}
            if not inv.get("id"):
                continue
            detail = {
                "invoiceId": inv.get("id"),
                "claimId": cl.get("id"),
                "claimNo": cl.get("claimNo", ""),
                "lineNo": ln.get("lineNo"),
                "invoiceCode": inv.get("invoiceCode", ""),
                "invoiceNo": inv.get("invoiceNo", ""),
                "invoiceKind": inv.get("invoiceKind", ""),
                "issuedOn": inv.get("issuedOn", ""),
                "buyerName": (inv.get("buyer") or {}).get("name", ""),
                "buyerTaxNo": (inv.get("buyer") or {}).get("taxNo", ""),
                "sellerName": (inv.get("seller") or {}).get("name", ""),
                "sellerTaxNo": (inv.get("seller") or {}).get("taxNo", ""),
                "totalFen": inv.get("totalFen"),
                "taxRate": inv.get("taxRate"),
                "attachmentId": (ln.get("attachment") or {}).get("id"),
                "migrated": (ln.get("attachment") or {}).get("migrated"),
            }
            inv_by_id.setdefault(inv["id"], detail)
            key = f"{inv.get('invoiceCode', '')}/{inv.get('invoiceNo', '')}"
            inv_by_key.setdefault(key, []).append(detail)

    # 台账兜底：非报销类发票（采购进项等）不在单据里，用台账记录补充
    ledger_file = os.path.join(
        Path(__file__).resolve().parents[3],
        "output", "cache", "invoice_ledger.json",
    )
    if os.path.exists(ledger_file):
        with open(ledger_file, "r", encoding="utf-8") as f:
            ledger = json.load(f)
        for inv in ledger:
            iid = inv.get("id")
            if iid and iid not in inv_by_id:
                inv_by_id[iid] = {
                    "invoiceId": iid,
                    "claimId": None,
                    "claimNo": None,
                    "lineNo": None,
                    "invoiceCode": inv.get("invoiceCode", ""),
                    "invoiceNo": inv.get("invoiceNo", ""),
                    "invoiceKind": inv.get("invoiceKind", ""),
                    "issuedOn": inv.get("issuedOn", ""),
                    "buyerName": (inv.get("buyer") or {}).get("name", ""),
                    "buyerTaxNo": (inv.get("buyer") or {}).get("taxNo", ""),
                    "sellerName": (inv.get("seller") or {}).get("name", ""),
                    "sellerTaxNo": (inv.get("seller") or {}).get("taxNo", ""),
                    "totalFen": inv.get("totalFen"),
                    "taxRate": inv.get("taxRate"),
                    "attachmentId": None,
                    "fromLedger": True,
                }
            # 台账中的重复键也补进 inv_by_key
            if iid:
                key = f"{inv.get('invoiceCode', '')}/{inv.get('invoiceNo', '')}"
            if key not in inv_by_key:
                inv_by_key[key] = [inv_by_id[iid]]

    return inv_by_id, inv_by_key


def _enrich_invoice_details(claims: list, result: dict) -> dict:
    """从全量单据缓存解析发票明细，附加到重复/票面问题条目（供前端下钻）"""
    inv_by_id, inv_by_key = _build_invoice_detail_map(claims)

    for dup in result.get("duplicateInvoices", []):
        key = f"{dup.get('invoiceCode', '')}/{dup.get('invoiceNo', '')}"
        dup["invoices"] = inv_by_key.get(key, [])
    for iss in result.get("invoiceIssues", []):
        d = inv_by_id.get(iss.get("invoiceId"))
        if d:
            iss["invoice"] = d
        if iss.get("issue") == "SUPPLIER_DUP" and iss.get("invoiceIds"):
            iss["invoices"] = [
                inv_by_id[iid] for iid in iss["invoiceIds"]
                if iid in inv_by_id
            ]
    for prof in result.get("supplierProfiles", []):
        prof["invoices"] = [
            inv_by_id[iid] for iid in prof.get("invoiceIds", [])
            if iid in inv_by_id
        ]
    return result


@router.post("/scan")
def scan_anomalies(req: ScanRequest):
    """执行 M3 全量发票异常检测（重复报销/抬头/税号/税率）"""
    import os
    import json
    from pathlib import Path
    report_path = os.path.join(
        Path(__file__).resolve().parents[3],
        "output", "reports", "m3_result.json",
    )
    # 页面加载默认返回最近一次结果（秒开）；useCached=False 强制重新全量扫描
    if req.useCached and os.path.exists(report_path):
        with open(report_path, "r", encoding="utf-8") as f:
            cached = json.load(f)
        return _enrich_from_cache(cached)
    try:
        from core.client import QihengClient
        from core.m3_processor import M3Processor
        from core.claim_store import fetch_all_claims
        client = QihengClient(api_key=req.apiKey, base_url=req.apiUrl or None)
        processor = M3Processor(client=client)
        results = processor.run(limit=req.limit)
        # 持久化原始扫描结果，供 AI 复核/缓存读取使用同一份数据
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        claims = fetch_all_claims(client)
        return _enrich_invoice_details(claims, results)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _enrich_from_cache(cached: dict) -> dict:
    """读取最近一次扫描结果并做发票明细解析（加载单据/台账缓存）"""
    import os
    import json
    from pathlib import Path
    report_path = os.path.join(
        Path(__file__).resolve().parents[3],
        "output", "reports", "m3_result.json",
    )
    data = dict(cached) if cached else {}
    if os.path.exists(report_path):
        with open(report_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    cache_file = os.path.join(
        Path(__file__).resolve().parents[3],
        "output", "cache", "all_claims.json",
    )
    claims = []
    if os.path.exists(cache_file):
        with open(cache_file, "r", encoding="utf-8") as f:
            claims = json.load(f)
    data["fromCache"] = True
    return _enrich_invoice_details(claims, data)


@router.post("/ai-review")
def ai_review_anomalies(req: AIReviewRequest):
    """AI 复核 M3 异常（异步任务，立即返回 jobId）"""
    req_data = req.model_dump()

    def worker(job_id: str) -> None:
        import os
        import json
        import time
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from pathlib import Path

        from core.llm_reviewer import LLMReviewer
        reviewer = LLMReviewer()

        scan = _enrich_from_cache({})
        tasks = []
        if req_data["scope"] in ("all", "issues"):
            tasks += [("issue", it) for it in scan.get("invoiceIssues", [])]
        if req_data["scope"] in ("all", "duplicates"):
            tasks += [("duplicate", it) for it in scan.get("duplicateInvoices", [])]

        results = {}
        failed = 0

        def _one(kind_item):
            kind, item = kind_item
            # sub 不含 kind 前缀，统一由外层拼成 "issue:TITLE_WRONG:INV-x" / "duplicate:CODE/NO"
            sub = (
                f"{item.get('issue')}:{item.get('invoiceId')}"
                if kind == "issue"
                else f"{item.get('invoiceCode')}/{item.get('invoiceNo')}"
            )
            try:
                out = reviewer.review_m3_anomaly(
                    _build_anomaly_payload(item, kind),
                    _anomaly_keywords(item, kind),
                )
                return kind, sub, out
            except Exception as e:
                return kind, sub, {"error": str(e)[:200]}

        done = 0
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(_one, t) for t in tasks]
            for fut in as_completed(futures):
                kind, sub, out = fut.result()
                results[f"{kind}:{sub}"] = out
                if out.get("error"):
                    failed += 1
                done += 1
                update_progress(job_id, len(tasks), done)

        review_path = os.path.join(
            Path(__file__).resolve().parents[3],
            "output", "reports", "m3_ai_review.json",
        )
        payload = {
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            "model": reviewer.model,
            "skill": "m3-ai-review",
            "scope": req_data["scope"],
            "total": len(tasks),
            "failed": failed,
            "results": results,
            "fromCache": False,
        }
        os.makedirs(os.path.dirname(review_path), exist_ok=True)
        with open(review_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        update_progress(job_id, len(tasks), len(tasks), results=payload)

    job_id = start_job("m3-ai-review", worker)
    return {"jobId": job_id, "status": "running"}


@router.get("/ai-review-status/{job_id}")
def ai_review_status(job_id: str):
    """查询 M3 AI 复核任务进度"""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    return job


@router.get("/ai-review-results")
def get_ai_review_results():
    """获取最近一次 AI 复核结果"""
    from pathlib import Path
    import os
    import json
    review_path = os.path.join(
        Path(__file__).resolve().parents[3],
        "output", "reports", "m3_ai_review.json",
    )
    if os.path.exists(review_path):
        with open(review_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"results": {}, "total": 0, "message": "尚未执行 AI 复核"}


@router.get("/results")
def get_anomaly_results():
    """获取最近一次异常检测结果"""
    import os
    import json
    from pathlib import Path
    report_path = os.path.join(
        Path(__file__).resolve().parents[3],
        "output", "reports", "m3_result.json",
    )
    if os.path.exists(report_path):
        with open(report_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"duplicateInvoices": [], "invoiceIssues": [], "message": "请先执行扫描"}


@router.post("/ai-scan")
def ai_scan_invoices(req: AIScanRequest):
    """AI 全量巡检（分批初筛，异步任务；limit 控制小批量演示）"""
    req_data = req.model_dump()

    def worker(job_id: str) -> None:
        import os
        import json
        from pathlib import Path
        ledger_file = os.path.join(
            Path(__file__).resolve().parents[3],
            "output", "cache", "invoice_ledger.json",
        )
        if req_data["useCached"] and os.path.exists(ledger_file):
            with open(ledger_file, "r", encoding="utf-8") as f:
                invoices = json.load(f)
        else:
            from core.client import QihengClient
            client = QihengClient(
                api_key=req_data["apiKey"], base_url=req_data["apiUrl"] or None
            )
            invoices = list(client.invoices_iterate())
            os.makedirs(os.path.dirname(ledger_file), exist_ok=True)
            with open(ledger_file, "w", encoding="utf-8") as f:
                json.dump(invoices, f, ensure_ascii=False)

        def cb(total: int, processed: int) -> None:
            update_progress(job_id, total, processed, phase="scan")

        from core.m3_ai_scan import run_full_scan
        report = run_full_scan(
            invoices,
            batch_size=max(1, req_data["batchSize"]),
            limit=req_data["limit"],
            max_workers=4,
            progress_cb=cb,
        )
        report["fromCache"] = bool(req_data["useCached"])
        scan_path = os.path.join(
            Path(__file__).resolve().parents[3],
            "output", "reports", "m3_ai_scan.json",
        )
        os.makedirs(os.path.dirname(scan_path), exist_ok=True)
        with open(scan_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        update_progress(
            job_id, report["batchCount"], report["batchCount"],
            results=report, phase="done",
        )

    job_id = start_job("m3-ai-scan", worker)
    return {"jobId": job_id, "status": "running"}


@router.get("/ai-scan-status/{job_id}")
def ai_scan_status(job_id: str):
    """查询 AI 全量巡检任务进度"""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    return job


@router.get("/ai-scan-results")
def get_ai_scan_results():
    """获取最近一次 AI 全量巡检结果（附带发票详情供下钻）"""
    import os
    import json
    from pathlib import Path
    scan_path = os.path.join(
        Path(__file__).resolve().parents[3],
        "output", "reports", "m3_ai_scan.json",
    )
    if not os.path.exists(scan_path):
        return {"results": {}, "flaggedCount": 0, "message": "尚未执行 AI 全量巡检"}
    with open(scan_path, "r", encoding="utf-8") as f:
        report = json.load(f)

    claims = []
    claims_file = os.path.join(
        Path(__file__).resolve().parents[3],
        "output", "cache", "all_claims.json",
    )
    if os.path.exists(claims_file):
        with open(claims_file, "r", encoding="utf-8") as f:
            claims = json.load(f)
    inv_by_id, _ = _build_invoice_detail_map(claims)

    flagged = []
    for iid, it in (report.get("results") or {}).items():
        entry = dict(it)
        entry["invoiceId"] = iid
        entry["invoice"] = inv_by_id.get(iid) or {}
        flagged.append(entry)
    report["flagged"] = flagged
    return report
